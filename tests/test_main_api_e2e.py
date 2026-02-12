from __future__ import annotations

from fastapi.testclient import TestClient

import finrag.main as mainmod


def test_health_endpoint() -> None:
    client = TestClient(mainmod.app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_generation_presets_endpoint() -> None:
    client = TestClient(mainmod.app)
    resp = client.get("/generation_presets")
    assert resp.status_code == 200
    payload = resp.json()
    assert "default_mode" in payload
    assert "presets" in payload
    assert isinstance(payload["presets"], list)


def test_query_endpoint_uses_service(monkeypatch) -> None:
    class DummyService:
        def __init__(self):
            self.calls = []

        def answer_question(
            self,
            *,
            question,
            settings,
            tickers=None,
            filing_date_from=None,
            filing_date_to=None,
            include_retrieved_chunks: bool = False,
        ):
            self.calls.append(
                {
                    "question": question,
                    "mode": settings.mode,
                    "top_k_retrieve": settings.top_k_retrieve,
                    "tickers": tickers,
                    "filing_date_from": filing_date_from,
                    "filing_date_to": filing_date_to,
                    "include_retrieved_chunks": include_retrieved_chunks,
                }
            )
            return mainmod.QueryResponse(draft_answer="D", final_answer="F", top_chunks=[], retrieved_chunks=None)

    svc = DummyService()
    monkeypatch.setattr(mainmod, "get_rag_service", lambda: svc)

    client = TestClient(mainmod.app)
    resp = client.post("/query", json={"question": "hello", "mode": "quick"})
    assert resp.status_code == 200
    assert resp.json()["final_answer"] == "F"
    assert svc.calls and svc.calls[0]["mode"] == "quick"


def test_cancel_endpoint_not_found_by_default() -> None:
    client = TestClient(mainmod.app)
    resp = client.post("/cancel", json={"request_id": "does-not-exist"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "not_found"
