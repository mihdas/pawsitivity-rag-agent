"""Test doubles: a scripted fake LLM and an in-memory search. No API key or Qdrant needed."""

import pytest
from langchain_core.documents import Document
from langchain_core.messages import AIMessage

from app.config import get_guardrails, get_settings
from app.graph import build_graph

KB = [
    (Document(page_content="Coexist with Pawsitivity helps families live happily with their dogs.",
              metadata={"title": "About", "url": "https://coexistwithpawsitivity.com/about"}),
     ["about", "what is", "pawsitivity"]),
    (Document(page_content="You can reach us at hello@example.org.",
              metadata={"title": "Contact", "url": "https://coexistwithpawsitivity.com/contact"}),
     ["contact", "reach", "email"]),
]


class FakeLLM:
    """Answers like Claude would, based on which prompt it receives."""

    def __init__(self, answer: str | None = None):
        self.answer = answer
        self.calls: list[str] = []

    def invoke(self, messages):
        system = messages[0].content
        user = messages[-1].content.lower()
        if "topic classifier" in system:
            self.calls.append("topic")
            if any(w in user for w in ("hi", "thanks", "hello")) and len(user) < 60:
                return AIMessage("SMALLTALK")
            if any(w in user for w in ("python", "capital", "election")):
                return AIMessage("OUT_OF_SCOPE")
            return AIMessage("IN_SCOPE")
        if "standalone search query" in system:
            self.calls.append("condense")
            return AIMessage(user + " contact")
        self.calls.append("answer")
        if self.answer is not None:
            return AIMessage(self.answer)
        return AIMessage("Coexist with Pawsitivity helps families live happily with their dogs.")


def fake_search(query: str, k: int):
    q = query.lower()
    hits = [(doc, 0.8) for doc, keys in KB if any(key in q for key in keys)]
    return (hits or [(KB[0][0], 0.1)])[:k]   # low score = irrelevant


@pytest.fixture
def make_graph():
    def _make(answer: str | None = None):
        llm = FakeLLM(answer)
        return build_graph(llm, fake_search, get_guardrails(), get_settings()), llm
    return _make
