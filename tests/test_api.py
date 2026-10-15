import pytest
from fastapi.testclient import TestClient

from app.main import app, limiter


@pytest.fixture
def client(make_graph):
    limiter.reset()   # rate-limit counters are shared between tests
    app.state.graph, _ = make_graph()
    with TestClient(app) as c:
        yield c
    app.state.graph = None


def test_chat_endpoint(client):
    r = client.post("/api/chat", json={"message": "What is Pawsitivity about?"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "answered"
    assert body["sources"]


def test_validation_rejects_huge_payload(client):
    r = client.post("/api/chat", json={"message": "x" * 5000})
    assert r.status_code == 422


def test_cors_only_allows_own_site(client):
    ok = client.options("/api/chat", headers={"Origin": "https://coexistwithpawsitivity.com",
                                                "Access-Control-Request-Method": "POST"})
    assert ok.headers.get("access-control-allow-origin") == "https://coexistwithpawsitivity.com"
    bad = client.options("/api/chat", headers={"Origin": "https://evil.example",
                                                 "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in bad.headers


def test_widget_and_health(client):
    assert client.get("/healthz").json() == {"ok": True}
    w = client.get("/widget.js")
    assert w.status_code == 200 and "attachShadow" in w.text
    assert "greeting" in client.get("/api/config").json()


def test_rate_limit(client):
    codes = [client.post("/api/chat", json={"message": "Hi"}).status_code for _ in range(25)]
    assert 429 in codes


def test_llm_failure_returns_friendly_503(client):
    class Broken:
        async def ainvoke(self, _):
            raise RuntimeError("Error code: 400 - temperature not supported")

    app.state.graph = Broken()
    r = client.post("/api/chat", json={"message": "What is Pawsitivity about?"})
    assert r.status_code == 503
    assert r.json()["status"] == "error" and "not available" in r.json()["answer"]


def test_ingest_on_start_retries_until_qdrant_is_up(monkeypatch):
    import scripts.ingest
    from app import main

    calls = []

    def flaky_ingest(**_):
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionError("qdrant not ready")
        return 5

    monkeypatch.setattr(scripts.ingest, "run_ingest", flaky_ingest)
    monkeypatch.setattr(main.time, "sleep", lambda _: None)
    monkeypatch.setattr(main.settings, "ingest_on_start", True)
    monkeypatch.setattr(main.settings, "anthropic_api_key", "test")
    app.state.graph = None
    with TestClient(app) as c:
        assert c.get("/healthz").status_code == 200
    assert len(calls) == 3
    app.state.graph = None
