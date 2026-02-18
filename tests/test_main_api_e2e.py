from __future__ import annotations

from fastapi.testclient import TestClient

import andromeda.main as mainmod
from andromeda.query.runtime import QueryStatus


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
            conversation_id: str | None = None,
            pre_tool_trace=None,
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
                    "conversation_id": conversation_id,
                    "pre_tool_trace": pre_tool_trace,
                }
            )
            return mainmod.QueryResponse(
                draft_answer="D",
                final_answer="F",
                top_chunks=[],
                retrieved_chunks=None,
                conversation_id=conversation_id,
            )

    svc = DummyService()
    monkeypatch.setattr(mainmod, "get_rag_service", lambda: svc)

    client = TestClient(mainmod.app)
    resp = client.post("/query", json={"question": "hello", "mode": "quick"})
    assert resp.status_code == 200
    assert resp.json()["final_answer"] == "F"
    assert svc.calls and svc.calls[0]["mode"] == "quick"
    assert isinstance(resp.json().get("conversation_id"), str)
    assert svc.calls[0]["pre_tool_trace"] == []


def test_query_endpoint_supports_clarification_followup(monkeypatch) -> None:
    mainmod._CONVERSATIONS.clear()

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
            conversation_id: str | None = None,
            pre_tool_trace=None,
        ):
            _ = settings, tickers, filing_date_from, filing_date_to, include_retrieved_chunks
            self.calls.append(
                {"question": question, "conversation_id": conversation_id, "pre_tool_trace": pre_tool_trace}
            )
            if "User clarification:" not in str(question):
                return mainmod.QueryResponse(
                    status=QueryStatus.CLARIFICATION_REQUIRED,
                    conversation_id=conversation_id,
                    clarifying_question="Which ticker should I use?",
                    draft_answer="Which ticker should I use?",
                    final_answer="Which ticker should I use?",
                    top_chunks=[],
                    retrieved_chunks=None,
                )
            return mainmod.QueryResponse(
                status=QueryStatus.ANSWERED,
                conversation_id=conversation_id,
                draft_answer="D",
                final_answer="F",
                top_chunks=[],
                retrieved_chunks=None,
            )

    svc = DummyService()
    monkeypatch.setattr(mainmod, "get_rag_service", lambda: svc)

    client = TestClient(mainmod.app)
    first = client.post("/query", json={"question": "Compare Google and Nvidia."})
    assert first.status_code == 200
    first_payload = first.json()
    assert first_payload["status"] == QueryStatus.CLARIFICATION_REQUIRED.value
    conversation_id = str(first_payload["conversation_id"])
    assert conversation_id

    second = client.post("/query", json={"question": "Use NVDA.", "conversation_id": conversation_id})
    assert second.status_code == 200
    second_payload = second.json()
    assert second_payload["status"] == QueryStatus.ANSWERED.value

    assert len(svc.calls) == 2
    assert "User clarification:" in svc.calls[1]["question"]
    assert "Use NVDA." in svc.calls[1]["question"]
    pre_tool_trace = svc.calls[1]["pre_tool_trace"]
    assert isinstance(pre_tool_trace, list)
    assert pre_tool_trace and getattr(pre_tool_trace[0], "tool", "") == "apply_user_clarification"


def test_cancel_endpoint_not_found_by_default() -> None:
    client = TestClient(mainmod.app)
    resp = client.post("/cancel", json={"request_id": "does-not-exist"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "not_found"


def test_ingest_endpoint_starts_ticker_job(monkeypatch) -> None:
    calls: list[tuple[list[str], int]] = []

    def fake_start_ticker_ingestion_job(*, tickers: list[str], per_company: int) -> mainmod.TickerIngestJobStatus:
        calls.append((list(tickers), per_company))
        return mainmod.TickerIngestJobStatus(
            job_id="job-123",
            tickers=["AMD", "NVDA"],
            per_company=3,
            status="queued",
            stage="queued",
            message="Job queued",
            created_at="2026-02-14T00:00:00+00:00",
        )

    monkeypatch.setattr(mainmod, "start_ticker_ingestion_job", fake_start_ticker_ingestion_job)

    client = TestClient(mainmod.app)
    resp = client.post("/ingest", json={"tickers": ["amd", "nvda"], "per_company": 3})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["job_id"] == "job-123"
    assert payload["status"] == "queued"
    assert payload["tickers"] == ["AMD", "NVDA"]
    assert calls == [(["amd", "nvda"], 3)]


def test_ingest_endpoint_returns_400_on_validation_error(monkeypatch) -> None:
    def fake_start_ticker_ingestion_job(*, tickers: list[str], per_company: int) -> mainmod.TickerIngestJobStatus:
        _ = tickers, per_company
        raise ValueError("Ticker is invalid")

    monkeypatch.setattr(mainmod, "start_ticker_ingestion_job", fake_start_ticker_ingestion_job)

    client = TestClient(mainmod.app)
    resp = client.post("/ingest", json={"ticker": "bad", "per_company": 1})
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Ticker is invalid"


def test_ingest_status_endpoint_uses_job_manager(monkeypatch) -> None:
    def fake_get_ticker_ingestion_job_status(job_id: str) -> mainmod.TickerIngestJobStatus | None:
        if job_id == "missing":
            return None
        return mainmod.TickerIngestJobStatus(
            job_id=job_id,
            tickers=["NVDA"],
            per_company=2,
            status="running",
            stage="chunk",
            message="Chunking markdown filings",
            created_at="2026-02-14T00:00:00+00:00",
            started_at="2026-02-14T00:00:01+00:00",
        )

    monkeypatch.setattr(mainmod, "get_ticker_ingestion_job_status", fake_get_ticker_ingestion_job_status)

    client = TestClient(mainmod.app)

    ok_resp = client.get("/ingest/job-abc")
    assert ok_resp.status_code == 200
    assert ok_resp.json()["stage"] == "chunk"

    missing_resp = client.get("/ingest/missing")
    assert missing_resp.status_code == 404
