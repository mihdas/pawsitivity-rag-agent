"""The RAG agent as a LangGraph state machine.

    input_guard ──blocked──────────────────────────────────────────────► END
        │ ok
    topic_check ──OUT_OF_SCOPE──► refuse ─────────────────────────────► END
        │       └─SMALLTALK─────► smalltalk ──────────────────────────► END
        │ IN_SCOPE
    condense (rewrites follow-up questions into a standalone question)
        │
    retrieve ──no chunk above min_relevance──► no_answer ─────────────► END
        │
    generate ──NO_ANSWER / leak──► no_answer | blocked ──────────────► END
        │
       END (answer + sources)
"""

from collections.abc import Callable
from typing import Literal, TypedDict

from langchain_core.documents import Document
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from app import guardrails
from app.config import GuardrailConfig, Settings
from app.prompts import ANSWER_SYSTEM, NO_ANSWER_TOKEN, TOPIC_CHECK_SYSTEM

SearchFn = Callable[[str, int], list[tuple[Document, float]]]
Status = Literal["answered", "refused", "no_answer", "blocked", "smalltalk"]


class ChatState(TypedDict, total=False):
    message: str
    history: list[dict]          # [{"role": "user"|"assistant", "content": str}, ...]
    label: str
    query: str
    docs: list[tuple[Document, float]]
    answer: str
    sources: list[dict]
    status: Status
    reason: str


def _history_messages(history: list[dict], limit: int) -> list[BaseMessage]:
    msgs: list[BaseMessage] = []
    for turn in history[-limit:]:
        content = str(turn.get("content", ""))[:1000]
        msgs.append(HumanMessage(content) if turn.get("role") == "user" else AIMessage(content))
    return msgs


def _text(msg) -> str:
    """Return only the text blocks of a model reply.

    Claude 5.5 replies can start with thinking blocks even when thinking is not requested,
    so `content` may be a list of blocks instead of a plain string.
    """
    content = msg.content
    if isinstance(content, str):
        return content.strip()
    parts = []
    for block in content or []:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "".join(parts).strip()


def _format_context(docs: list[tuple[Document, float]]) -> str:
    parts = []
    for i, (doc, _score) in enumerate(docs, 1):
        title = doc.metadata.get("title", "")
        url = doc.metadata.get("url", "")
        parts.append(f'<source id="{i}" title="{title}" url="{url}">\n{doc.page_content}\n</source>')
    return "\n\n".join(parts)


def _sources(docs: list[tuple[Document, float]]) -> list[dict]:
    seen, out = set(), []
    for doc, score in docs:
        key = doc.metadata.get("url") or doc.metadata.get("title")
        if key and key not in seen:
            seen.add(key)
            out.append({"title": doc.metadata.get("title", ""), "url": doc.metadata.get("url", ""),
                        "score": round(float(score), 3)})
    return out


def build_graph(llm: BaseChatModel, search: SearchFn, cfg: GuardrailConfig, settings: Settings):
    hist_limit = settings.max_history_turns

    def input_guard(state: ChatState) -> ChatState:
        res = guardrails.input_check(state["message"], cfg, settings.max_message_chars)
        if res.ok:
            return {}
        return {"status": "blocked", "reason": res.reason, "answer": cfg.blocked_message, "sources": []}

    def topic_check(state: ChatState) -> ChatState:
        system = TOPIC_CHECK_SYSTEM.format(site_name=cfg.site_name, scope_description=cfg.scope_description)
        msgs = [SystemMessage(system), *_history_messages(state.get("history", []), hist_limit),
                HumanMessage(f"<visitor_message>{state['message']}</visitor_message>")]
        return {"label": guardrails.parse_topic_label(_text(llm.invoke(msgs)))}

    def refuse(state: ChatState) -> ChatState:
        return {"status": "refused", "reason": "out_of_scope", "answer": cfg.refusal_message, "sources": []}

    def smalltalk(state: ChatState) -> ChatState:
        return {"status": "smalltalk", "answer": cfg.greeting_message, "sources": []}

    def condense(state: ChatState) -> ChatState:
        history = state.get("history", [])
        if not history:
            return {"query": state["message"]}
        msgs = [SystemMessage("Rewrite the visitor's last message as a standalone search query, using the "
                              "conversation for context. Reply with the query only."),
                *_history_messages(history, hist_limit), HumanMessage(state["message"])]
        query = _text(llm.invoke(msgs))
        return {"query": (query or state["message"])[:500]}

    def retrieve(state: ChatState) -> ChatState:
        hits = search(state["query"], settings.top_k)
        relevant = [(d, s) for d, s in hits if s >= settings.min_relevance]
        return {"docs": relevant}

    def no_answer(state: ChatState) -> ChatState:
        return {"status": "no_answer", "reason": state.get("reason") or "no_relevant_context",
                "answer": cfg.no_answer_message, "sources": []}

    def generate(state: ChatState) -> ChatState:
        system = ANSWER_SYSTEM.format(assistant_name=cfg.assistant_name, site_name=cfg.site_name,
                                      no_answer_token=NO_ANSWER_TOKEN, context=_format_context(state["docs"]))
        msgs = [SystemMessage(system), *_history_messages(state.get("history", []), hist_limit),
                HumanMessage(state["message"])]
        answer = _text(llm.invoke(msgs))
        if not answer or NO_ANSWER_TOKEN in answer:   # empty = refusal or cut off
            return {"status": "no_answer", "reason": "model_no_answer", "answer": cfg.no_answer_message, "sources": []}
        if not guardrails.output_check(answer).ok:
            return {"status": "blocked", "reason": "output_check", "answer": cfg.blocked_message, "sources": []}
        return {"status": "answered", "answer": answer, "sources": _sources(state["docs"])}

    g = StateGraph(ChatState)
    for name, fn in [("input_guard", input_guard), ("topic_check", topic_check), ("refuse", refuse),
                     ("smalltalk", smalltalk), ("condense", condense), ("retrieve", retrieve),
                     ("no_answer", no_answer), ("generate", generate)]:
        g.add_node(name, fn)

    g.add_edge(START, "input_guard")
    g.add_conditional_edges("input_guard", lambda s: END if s.get("status") == "blocked" else "topic_check")
    g.add_conditional_edges("topic_check", lambda s: {"IN_SCOPE": "condense", "SMALLTALK": "smalltalk"}
                            .get(s["label"], "refuse"))
    g.add_edge("condense", "retrieve")
    g.add_conditional_edges("retrieve", lambda s: "generate" if s["docs"] else "no_answer")
    for terminal in ("refuse", "smalltalk", "no_answer", "generate"):
        g.add_edge(terminal, END)
    return g.compile()


def default_graph():
    """Graph wired to Claude + Qdrant. Used by the API and the eval script."""
    from langchain_anthropic import ChatAnthropic

    from app.config import get_guardrails, get_settings
    from app.vectorstore import get_client, get_vectorstore

    s = get_settings()
    kwargs = {"model": s.llm_model, "max_tokens": s.llm_max_tokens, "api_key": s.anthropic_api_key,
              "timeout": 30, "max_retries": 2}
    if s.llm_temperature is not None:
        kwargs["temperature"] = s.llm_temperature
    llm = ChatAnthropic(**kwargs)
    store = None

    def search(query: str, k: int) -> list[tuple[Document, float]]:
        # Connect lazily: the API starts even before the first ingestion has created the collection.
        nonlocal store
        if store is None:
            if not get_client().collection_exists(s.collection):
                return []
            store = get_vectorstore()
        return store.similarity_search_with_score(query, k=k)

    return build_graph(llm, search, get_guardrails(), s)
