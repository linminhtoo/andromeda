from __future__ import annotations

from datetime import datetime, timezone

from andromeda.eval.ground_truth_validation import validate_factual_queries_with_edgar
from andromeda.eval.schema import EvidenceChunk, EvalQuery, FactualSpec, NumericAnswer, ScaleUnits
from andromeda.finance_tools import FinanceToolResult, FinanceToolStatus, FinanceTools


def _factual_query(*, metric: str, value: float, scale: ScaleUnits | None = "units", ticker: str = "AAPL") -> EvalQuery:
    now = datetime.now(timezone.utc)
    return EvalQuery(
        id=f"fact-{metric}-{ticker}",
        kind="factual",
        question=f"What was {ticker} {metric}?",
        tags=["factual", ticker],
        created_at=now,
        factual=FactualSpec(
            metric=metric,
            expected_numeric=NumericAnswer(value=value, unit="USD", scale=scale),
            golden_evidence=EvidenceChunk(doc_id=f"{ticker}_doc", chunk_id="chunk-1"),
        ),
        generator={"source": "test"},
    )


def test_validate_factual_queries_with_edgar_marks_match(monkeypatch) -> None:
    def fake_fetch(self: FinanceTools, *, ticker: str):
        return [
            FinanceToolResult(
                tool="edgar_get_financial_metrics",
                ticker=ticker,
                status=FinanceToolStatus.OK,
                summary="ok",
                payload={"metrics": {"revenue": 100_000_000.0}},
            )
        ]

    monkeypatch.setattr(FinanceTools, "fetch_edgar_financials", fake_fetch)

    query = _factual_query(metric="total revenue", value=100.0, scale="millions", ticker="AAPL")
    kept, stats = validate_factual_queries_with_edgar([query], rel_tol=0.2, drop_mismatched=False)

    assert len(kept) == 1
    assert stats.validated == 1
    assert stats.matched == 1
    assert stats.mismatched == 0
    assert kept[0].generator["edgar_validation"]["status"] == "matched"


def test_validate_factual_queries_with_edgar_can_drop_mismatched(monkeypatch) -> None:
    def fake_fetch(self: FinanceTools, *, ticker: str):
        return [
            FinanceToolResult(
                tool="edgar_get_financial_metrics",
                ticker=ticker,
                status=FinanceToolStatus.OK,
                summary="ok",
                payload={"metrics": {"revenue": 20_000_000.0}},
            )
        ]

    monkeypatch.setattr(FinanceTools, "fetch_edgar_financials", fake_fetch)

    query = _factual_query(metric="total revenue", value=100.0, scale="millions", ticker="AAPL")
    kept, stats = validate_factual_queries_with_edgar([query], rel_tol=0.2, drop_mismatched=True)

    assert kept == []
    assert stats.validated == 1
    assert stats.matched == 0
    assert stats.mismatched == 1
    assert stats.dropped_mismatched == 1


def test_validate_factual_queries_with_edgar_can_match_when_scale_hint_missing(monkeypatch) -> None:
    def fake_fetch(self: FinanceTools, *, ticker: str):
        return [
            FinanceToolResult(
                tool="edgar_get_financial_metrics",
                ticker=ticker,
                status=FinanceToolStatus.OK,
                summary="ok",
                payload={"metrics": {"revenue": 100_000_000.0}},
            )
        ]

    monkeypatch.setattr(FinanceTools, "fetch_edgar_financials", fake_fetch)

    query = _factual_query(metric="total revenue", value=100.0, scale="units", ticker="AAPL")
    kept, stats = validate_factual_queries_with_edgar([query], rel_tol=0.2, drop_mismatched=False)

    assert len(kept) == 1
    assert stats.validated == 1
    assert stats.matched == 1
    assert kept[0].generator["edgar_validation"]["status"] == "matched"
    assert kept[0].generator["edgar_validation"]["best_expected_scale"] == "millions"


def test_validate_factual_queries_with_edgar_skips_unsupported_metric(monkeypatch) -> None:
    def fake_fetch(self: FinanceTools, *, ticker: str):
        return [
            FinanceToolResult(
                tool="edgar_get_financial_metrics",
                ticker=ticker,
                status=FinanceToolStatus.OK,
                summary="ok",
                payload={"metrics": {"operating_income": 42.0}},
            )
        ]

    monkeypatch.setattr(FinanceTools, "fetch_edgar_financials", fake_fetch)

    query = _factual_query(metric="operating income", value=42.0, scale="units", ticker="AAPL")
    kept, stats = validate_factual_queries_with_edgar([query], rel_tol=0.2, drop_mismatched=True)

    assert len(kept) == 1
    assert stats.validated == 0
    assert stats.skipped_unsupported_metric == 1
    assert kept[0].generator["edgar_validation"]["status"] == "skipped_unsupported_metric"
