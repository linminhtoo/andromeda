from __future__ import annotations

import signal
import time
from pathlib import Path
from threading import Thread
from types import SimpleNamespace

import pytest

from finrag.eval.runner import RunConfig, _query_timeout_guard, run_generation, run_one
from finrag.eval.schema import EvalGeneration, EvalQuery, OpenEndedSpec


def _open_ended_query(query_id: str) -> EvalQuery:
    return EvalQuery(
        id=query_id,
        kind="open_ended",
        question=f"Question for {query_id} in 2025",
        open_ended=OpenEndedSpec(target_ticker="AAPL", target_year=2025),
    )


def test_query_timeout_guard_raises_when_time_exceeded() -> None:
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("SIGALRM not available on this platform")

    with pytest.raises(TimeoutError):
        with _query_timeout_guard(0.05):
            time.sleep(0.2)


def test_query_timeout_guard_noop_for_none() -> None:
    with _query_timeout_guard(None):
        time.sleep(0.01)


def test_query_timeout_guard_is_noop_in_non_main_thread() -> None:
    errors: list[Exception] = []

    def worker() -> None:
        try:
            with _query_timeout_guard(0.01):
                time.sleep(0.02)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    t = Thread(target=worker)
    t.start()
    t.join()
    assert errors == []


def test_run_generation_thread_backend_runs_all_queries(monkeypatch, tmp_path: Path) -> None:
    queries = [_open_ended_query("q1"), _open_ended_query("q2"), _open_ended_query("q3")]

    monkeypatch.setattr("finrag.main.get_rag_service", lambda: object())

    def fake_run_one(_service, query_id, kind, question, _settings, _cfg):
        generation = EvalGeneration(
            query_id=query_id,
            kind=kind,
            question=question,
            final_answer=f"answer-{query_id}",
        )
        generation.timing_ms["total_ms"] = 1.0
        return generation, 1.0, True

    monkeypatch.setattr("finrag.eval.runner.run_one", fake_run_one)

    out_path = tmp_path / "generations.jsonl"
    cfg = RunConfig(concurrency=2, parallel_backend="thread")
    summary = run_generation(queries, out_jsonl=out_path, cfg=cfg)

    assert summary["n"] == 3
    assert summary["n_ok"] == 3
    lines = [line for line in out_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 3
    dumped = [EvalGeneration.model_validate_json(line) for line in lines]
    assert [item.query_id for item in dumped] == ["q1", "q2", "q3"]


def test_run_one_thread_timeout_does_not_hang() -> None:
    class SlowService:
        def answer_question(self, _question, _settings, include_retrieved_chunks):  # noqa: ANN001
            _ = include_retrieved_chunks
            time.sleep(0.2)
            return SimpleNamespace(
                top_chunks=[],
                retrieved_chunks=[],
                draft_answer="",
                final_answer="",
            )

    settings = RunConfig(mode="quick").resolved_settings()
    cfg = RunConfig(mode="quick", query_timeout_s=0.05)
    holder: list[tuple[EvalGeneration, float, bool]] = []

    def worker() -> None:
        holder.append(run_one(SlowService(), "q-timeout", "open_ended", "question", settings, cfg))

    t = Thread(target=worker)
    t.start()
    t.join(timeout=1.0)
    assert not t.is_alive()
    assert len(holder) == 1
    generation, _ms, ok = holder[0]
    assert ok is False
    assert generation.error is not None
    assert "Timed out" in generation.error
