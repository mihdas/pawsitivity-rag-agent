"""HTTP API + chat widget."""

import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.config import get_guardrails, get_settings

log = logging.getLogger("pawsitivity")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

settings = get_settings()
STATIC = Path(__file__).parent / "static"


def client_ip(request: Request) -> str:
    # Behind the Kubernetes ingress the real client IP is in X-Forwarded-For.
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else get_remote_address(request)


limiter = Limiter(key_func=client_ip)


def _ingest_with_retries() -> None:
    from scripts.ingest import run_ingest

    for attempt in range(1, settings.ingest_retries + 1):
        try:
            run_ingest()
            return
        except Exception as exc:  # Qdrant not reachable yet
            log.warning("ingest attempt %d failed: %s: %s", attempt, type(exc).__name__, str(exc)[:200])
            time.sleep(min(3 * attempt, 15))
    raise RuntimeError("ingestion failed, giving up")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if getattr(app.state, "graph", None) is None:   # tests inject their own graph
        if settings.ingest_on_start:
            await asyncio.to_thread(_ingest_with_retries)
        from app.graph import default_graph
        app.state.graph = default_graph()
    yield


app = FastAPI(title="Pawsitivity RAG Agent", version="0.1.0", lifespan=lifespan,
              docs_url=None, redoc_url=None)
app.state.limiter = limiter
app.add_middleware(CORSMiddleware, allow_origins=settings.origins, allow_methods=["POST", "GET"],
                   allow_headers=["Content-Type"], max_age=3600)


@app.exception_handler(RateLimitExceeded)
async def rate_limited(request: Request, exc: RateLimitExceeded):
    return JSONResponse(status_code=429, content={"detail": "Too many messages. Please wait a moment."})


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=2000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[Turn] = Field(default_factory=list, max_length=20)


class Source(BaseModel):
    title: str
    url: str
    score: float


class ChatResponse(BaseModel):
    answer: str
    status: str
    sources: list[Source]
    request_id: str


@app.post("/api/chat", response_model=ChatResponse)
@limiter.limit(settings.rate_limit)
async def chat(request: Request, body: ChatRequest) -> ChatResponse:
    rid = uuid.uuid4().hex[:12]
    t0 = time.perf_counter()
    try:
        state = await request.app.state.graph.ainvoke(
            {"message": body.message, "history": [t.model_dump() for t in body.history]})
    except Exception as exc:  # LLM or vector DB unavailable, invalid API key, ...
        # Log the error type and details, but never the visitor's message.
        log.error("chat rid=%s failed: %s: %s", rid, type(exc).__name__, str(exc)[:500])
        return JSONResponse(status_code=503, content={
            "answer": "Sorry, the assistant is not available right now. Please try again later.",
            "status": "error", "sources": [], "request_id": rid})
    # Log metadata only, never the visitor's message (privacy / GDPR).
    log.info("chat rid=%s status=%s reason=%s label=%s docs=%d ms=%d", rid, state.get("status"),
             state.get("reason", ""), state.get("label", ""), len(state.get("docs", []) or []),
             (time.perf_counter() - t0) * 1000)
    return ChatResponse(answer=state["answer"], status=state["status"], sources=state.get("sources", []),
                        request_id=rid)


@app.get("/api/config")
async def public_config():
    g = get_guardrails()
    return {"assistant_name": g.assistant_name, "greeting": g.greeting_message.strip()}


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.get("/widget.js")
async def widget():
    return FileResponse(STATIC / "widget.js", media_type="application/javascript",
                        headers={"Cache-Control": "public, max-age=300"})
