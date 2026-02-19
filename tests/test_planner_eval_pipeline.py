from __future__ import annotations

import time
from types import SimpleNamespace

from andromeda.eval.planner_dataset import build_manual_planner_eval_queries
from andromeda.eval.planner_schema import (
    PlannerEvalAction,
    PlannerEvalCharacteristic,
    PlannerEvalPrediction,
    PlannerEvalQuery,
)
from andromeda.eval.planner_scoring import score_planner_predictions
from andromeda.query.runtime import QueryCharacteristic, QueryStatus
from scripts.run_planner_eval import PlannerRunConfig, run_one


def test_manual_planner_eval_dataset_shape() -> None:
    rows = build_manual_planner_eval_queries()
    assert len(rows) == 100
    assert len({item.id for item in rows}) == 100
    assert all(item.rationale is not None and item.rationale.strip() for item in rows)

    refused = sum(1 for item in rows if item.expected_action == PlannerEvalAction.REFUSED)
    clarifications = sum(1 for item in rows if item.expected_action == PlannerEvalAction.CLARIFICATION_REQUIRED)
    none = sum(1 for item in rows if item.expected_action is None)
    assert refused == 4
    assert clarifications == 2
    assert none == 94


def test_score_planner_predictions_perfect_match() -> None:
    queries = [
        PlannerEvalQuery(
            id="q1",
            question="What is AAPL market cap?",
            expected_characteristics=[PlannerEvalCharacteristic.MARKET_DATA, PlannerEvalCharacteristic.SIMPLE_NUMERIC],
        ),
        PlannerEvalQuery(
            id="q2",
            question="Refuse this",
            expected_characteristics=[],
            expected_action=PlannerEvalAction.REFUSED,
        ),
    ]
    predictions = [
        PlannerEvalPrediction(
            query_id="q1",
            question=queries[0].question,
            predicted_characteristics=[
                PlannerEvalCharacteristic.MARKET_DATA,
                PlannerEvalCharacteristic.SIMPLE_NUMERIC,
            ],
            predicted_action=PlannerEvalAction.ANSWERED,
        ),
        PlannerEvalPrediction(
            query_id="q2",
            question=queries[1].question,
            predicted_characteristics=[],
            predicted_action=PlannerEvalAction.REFUSED,
        ),
    ]

    scores, summary = score_planner_predictions(queries=queries, predictions=predictions)
    assert len(scores) == 2
    assert summary["n_queries"] == 2
    assert summary["missing_predictions"] == 0
    assert summary["prediction_errors"] == 0
    assert summary["characteristic_exact_match_rate"] == 1.0
    assert summary["expected_subset_recall_rate"] == 1.0
    assert summary["macro_precision"] == 1.0
    assert summary["macro_recall"] == 1.0
    assert summary["macro_f1"] == 1.0
    assert summary["micro_precision"] == 1.0
    assert summary["micro_recall"] == 1.0
    assert summary["micro_f1"] == 1.0
    assert summary["action_accuracy"] == 1.0


def test_score_planner_predictions_handles_missing_and_partial() -> None:
    queries = [
        PlannerEvalQuery(
            id="q1",
            question="What is AAPL market cap?",
            expected_characteristics=[PlannerEvalCharacteristic.MARKET_DATA, PlannerEvalCharacteristic.SIMPLE_NUMERIC],
        ),
        PlannerEvalQuery(
            id="q2",
            question="Write a poem",
            expected_characteristics=[],
            expected_action=PlannerEvalAction.REFUSED,
        ),
    ]
    predictions = [
        PlannerEvalPrediction(
            query_id="q1",
            question=queries[0].question,
            predicted_characteristics=[PlannerEvalCharacteristic.MARKET_DATA],
            predicted_action=PlannerEvalAction.ANSWERED,
            error="transient issue",
        )
    ]

    scores, summary = score_planner_predictions(queries=queries, predictions=predictions)
    assert len(scores) == 2
    assert summary["missing_predictions"] == 1
    assert summary["prediction_errors"] == 1
    assert summary["characteristic_exact_match_rate"] == 0.5
    assert summary["expected_subset_recall_rate"] == 0.5
    assert summary["action_accuracy"] == 0.0

    q1_score = next(item for item in scores if item.query_id == "q1")
    assert q1_score.missing_characteristics == [PlannerEvalCharacteristic.SIMPLE_NUMERIC]
    assert q1_score.extra_characteristics == []

    q2_score = next(item for item in scores if item.query_id == "q2")
    assert q2_score.prediction_error == "missing_prediction"


def test_run_one_maps_planner_output() -> None:
    class FakeService:
        def plan_query(self, question, tickers, filing_date_from, filing_date_to):  # noqa: ANN001
            _ = (question, tickers, filing_date_from, filing_date_to)
            return SimpleNamespace(
                characteristics=[QueryCharacteristic.MARKET_DATA, QueryCharacteristic.SIMPLE_NUMERIC],
                status=QueryStatus.ANSWERED,
                tickers=["aapl"],
                use_rag=False,
                use_yfinance=True,
                use_edgar_financials=False,
                use_per_ticker_retrieval=False,
                use_multi_ticker_briefs=False,
            )

    query = PlannerEvalQuery(
        id="q1",
        question="What is AAPL market cap?",
        expected_characteristics=[PlannerEvalCharacteristic.MARKET_DATA],
        explicit_tickers=["AAPL"],
    )
    prediction, _item_ms, ok = run_one(FakeService(), query, PlannerRunConfig(concurrency=1, query_timeout_s=2.0))
    assert ok is True
    assert prediction.error is None
    assert prediction.predicted_action == PlannerEvalAction.ANSWERED
    assert prediction.predicted_characteristics == [
        PlannerEvalCharacteristic.MARKET_DATA,
        PlannerEvalCharacteristic.SIMPLE_NUMERIC,
    ]
    assert prediction.predicted_tickers == ["AAPL"]
    assert prediction.use_yfinance is True


def test_run_one_retries_timeout_once() -> None:
    class SlowThenFastService:
        def __init__(self) -> None:
            self.calls = 0

        def plan_query(self, question, tickers, filing_date_from, filing_date_to):  # noqa: ANN001
            _ = (question, tickers, filing_date_from, filing_date_to)
            self.calls += 1
            if self.calls == 1:
                time.sleep(0.15)
            return SimpleNamespace(
                characteristics=[QueryCharacteristic.FINANCIAL_METRICS],
                status=QueryStatus.ANSWERED,
                tickers=["MSFT"],
                use_rag=True,
                use_yfinance=False,
                use_edgar_financials=True,
                use_per_ticker_retrieval=False,
                use_multi_ticker_briefs=False,
            )

    service = SlowThenFastService()
    query = PlannerEvalQuery(
        id="q-timeout",
        question="What was MSFT revenue in 2024?",
        expected_characteristics=[PlannerEvalCharacteristic.FINANCIAL_METRICS],
    )
    cfg = PlannerRunConfig(concurrency=1, query_timeout_s=0.05, query_max_retries=1)
    prediction, _item_ms, ok = run_one(service, query, cfg)

    assert ok is True
    assert prediction.error is None
    assert prediction.attempts == 2
    assert service.calls == 2


def test_run_one_records_terminal_error_after_retries() -> None:
    class AlwaysFailService:
        def plan_query(self, question, tickers, filing_date_from, filing_date_to):  # noqa: ANN001
            _ = (question, tickers, filing_date_from, filing_date_to)
            raise RuntimeError("planner failure")

    query = PlannerEvalQuery(
        id="q-fail",
        question="Anything",
        expected_characteristics=[],
    )
    prediction, _item_ms, ok = run_one(
        AlwaysFailService(),
        query,
        PlannerRunConfig(concurrency=1, query_timeout_s=2.0, query_max_retries=1),
    )

    assert ok is False
    assert prediction.error == "planner failure"
    assert prediction.attempts == 1
