from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import date
from typing import Any

import pytest

from andromeda.dataclasses import DocChunk, ScoredChunk
from andromeda.finance_tools import FinanceToolResult, FinanceToolStatus
from andromeda.llm.generation_controls import resolve_generation_settings
from andromeda.query.runtime import PlannerAction, PlannerDecision, QueryCharacteristic, QueryStatus, RAGService
from andromeda.retrieval.db import IngestedCompanyRow, RetrievalFilters
from tests.fakes import RecordingLLM


class FakeRetriever:
    retrieval_text_key = "retrieval_text"

    def __init__(self) -> None:
        self.retrieve_calls = 0
        self.last_filing_date_from: str | None = None
        self.last_filing_date_to: str | None = None

    def list_ingested_companies(self) -> list[IngestedCompanyRow]:
        return [
            IngestedCompanyRow(ticker="AAPL", company="Apple Inc."),
            IngestedCompanyRow(ticker="NVDA", company="NVIDIA Corporation"),
            IngestedCompanyRow(ticker="GOOGL", company="Alphabet Inc."),
        ]

    def build_filters(
        self, *, tickers: list[str] | None, filing_date_from: str | None, filing_date_to: str | None
    ) -> RetrievalFilters:
        self.last_filing_date_from = filing_date_from
        self.last_filing_date_to = filing_date_to
        parsed_from = date.fromisoformat(filing_date_from) if filing_date_from else None
        parsed_to = date.fromisoformat(filing_date_to) if filing_date_to else None
        if tickers is None:
            return RetrievalFilters(filing_date_from=parsed_from, filing_date_to=parsed_to)
        return RetrievalFilters(tickers=tuple(tickers), filing_date_from=parsed_from, filing_date_to=parsed_to)

    def retrieve_hybrid(
        self, _question: str, *, top_k_semantic: int, top_k_bm25: int, top_k_final: int, filters: RetrievalFilters
    ) -> list[ScoredChunk]:
        _ = top_k_semantic, top_k_bm25, top_k_final, filters
        self.retrieve_calls += 1
        ticker = str(filters.tickers[0]).upper() if filters.tickers else "AAPL"
        return [
            ScoredChunk(
                chunk=DocChunk(
                    id=f"chunk-{ticker}-{self.retrieve_calls}",
                    doc_id=f"doc-{ticker}",
                    text=f"{ticker} revenue grew 20% in 2025.",
                    page_no=None,
                    headings=["Item 7"],
                    source=f"{ticker.lower()}_10k.md",
                    metadata={"retrieval_text": f"{ticker} revenue grew 20% in 2025.", "doc": {"ticker": ticker}},
                ),
                score=1.0,
                source="hybrid",
            )
        ]

    def text_for_rerank(self, scored: ScoredChunk) -> str:
        return scored.chunk.text


class FakeReranker:
    def rerank(
        self, _question: str, hybrid: list[ScoredChunk], *, top_k: int, candidate_text_provider
    ) -> list[ScoredChunk]:
        _ = candidate_text_provider
        return hybrid[:top_k]


@dataclass
class FakeFinanceTools:
    calls: int = 0
    status: FinanceToolStatus = FinanceToolStatus.OK
    summary: str = "Fetched snapshot."
    payload: object | None = None

    def fetch_for_plan(
        self, *, question: str, tickers: list[str], use_yfinance: bool, use_edgar_financials: bool
    ) -> list[FinanceToolResult]:
        _ = question, use_yfinance, use_edgar_financials
        self.calls += 1
        return [
            FinanceToolResult(
                tool="yfinance_get_ticker_info",
                ticker=tickers[0] if tickers else None,
                status=self.status,
                summary=self.summary,
                payload=(self.payload if self.payload is not None else {"market": {"currentPrice": 210.0}}),
            )
        ]

    def tool_context_text(self, results: list[FinanceToolResult], *, max_chars: int = 14_000) -> str:
        _ = max_chars
        if not results:
            return ""
        return "TOOL CONTEXT"


PlannerOutput = PlannerDecision | str | Exception


def planner_decision_payload(decision: PlannerDecision) -> str:
    """
    Serialize planner decision for fake LLM response.
    """

    return decision.model_dump_json()


def build_service(
    finance_tools: FakeFinanceTools, *, planner_outputs: list[PlannerOutput] | None = None, answer_text: str = "answer"
) -> tuple[RAGService, FakeRetriever, RecordingLLM]:
    outputs = deque(planner_outputs or [])

    def chat_fn(_messages: list[dict[str, Any]], _temperature: float, response_model: Any) -> str:
        if response_model is PlannerDecision:
            if not outputs:
                raise RuntimeError("No planner output configured for this test.")
            item = outputs.popleft()
            if isinstance(item, Exception):
                raise item
            if isinstance(item, PlannerDecision):
                return planner_decision_payload(item)
            return str(item)
        return answer_text

    llm = RecordingLLM(chat_fn=chat_fn)
    retriever = FakeRetriever()
    service = RAGService(
        llm=llm,
        retriever=retriever,
        reranker=FakeReranker(),
        context_key="retrieval_context",
        finance_tools=finance_tools,
    )
    return service, retriever, llm


def generation_calls(llm: RecordingLLM) -> list[dict[str, Any]]:
    """
    Return non-planner LLM generation calls.
    """

    return [call for call in llm.chat_calls if call["response_model"] is None]


def test_tools_only_plan_skips_rag_and_still_answers() -> None:
    finance_tools = FakeFinanceTools()
    service, retriever, llm = build_service(
        finance_tools,
        planner_outputs=[
            PlannerDecision(
                action=PlannerAction.ANSWER,
                tickers=["AAPL"],
                use_rag=False,
                use_yfinance=True,
                use_edgar_financials=True,
            )
        ],
    )

    settings = resolve_generation_settings(mode="quick")
    pipeline = service.execute_query_pipeline(question="What is AAPL's latest valuation?", settings=settings)

    assert pipeline.planned.status == QueryStatus.ANSWERED
    assert pipeline.planned.use_rag is False
    assert len(pipeline.tool_results) == 1
    assert retriever.retrieve_calls == 0
    assert finance_tools.calls == 1

    response = service.response_from_pipeline(pipeline=pipeline, settings=settings)
    assert response.status == QueryStatus.ANSWERED
    assert len(response.tool_results) == 1
    assert response.tool_results[0].tool == "yfinance_get_ticker_info"

    calls = generation_calls(llm)
    assert len(calls) == 1
    assert "Tool Context:\nTOOL CONTEXT" in calls[0]["messages"][1]["content"]


def test_tools_plus_rag_runs_retrieval() -> None:
    finance_tools = FakeFinanceTools()
    service, retriever, _llm = build_service(
        finance_tools,
        planner_outputs=[
            PlannerDecision(
                action=PlannerAction.ANSWER,
                tickers=["AAPL"],
                use_rag=True,
                use_yfinance=True,
                use_edgar_financials=False,
            )
        ],
    )

    settings = resolve_generation_settings(mode="quick")
    pipeline = service.execute_query_pipeline(
        question="Compare AAPL filing context and market moves", settings=settings
    )

    assert pipeline.planned.status == QueryStatus.ANSWERED
    assert pipeline.planned.use_rag is True
    assert finance_tools.calls == 1
    assert retriever.retrieve_calls == 1
    assert len(pipeline.reranked) == 1


def test_finance_tools_can_be_disabled_by_env(monkeypatch) -> None:
    finance_tools = FakeFinanceTools()
    service, retriever, _llm = build_service(
        finance_tools,
        planner_outputs=[
            PlannerDecision(
                action=PlannerAction.ANSWER,
                tickers=["AAPL"],
                use_rag=True,
                use_yfinance=True,
                use_edgar_financials=True,
            )
        ],
    )
    monkeypatch.setenv("FINRAG_DISABLE_FINANCE_TOOLS", "1")

    settings = resolve_generation_settings(mode="quick")
    pipeline = service.execute_query_pipeline(question="What was AAPL revenue in the latest filing?", settings=settings)

    assert pipeline.planned.status == QueryStatus.ANSWERED
    assert finance_tools.calls == 0
    assert retriever.retrieve_calls == 1
    assert any(event.tool == "finance_tools_skip" for event in pipeline.tool_trace)


def test_multi_ticker_briefs_path_generates_parallel_briefs() -> None:
    finance_tools = FakeFinanceTools()
    service, retriever, llm = build_service(
        finance_tools,
        planner_outputs=[
            PlannerDecision(
                action=PlannerAction.ANSWER,
                tickers=["NVDA", "GOOGL"],
                use_rag=True,
                use_yfinance=False,
                use_edgar_financials=False,
                use_per_ticker_retrieval=True,
                use_multi_ticker_briefs=True,
            )
        ],
    )

    settings = resolve_generation_settings(mode="normal", enable_refine=False)
    pipeline = service.execute_query_pipeline(
        question="Compare NVDA vs GOOGL as long-term investments.", settings=settings
    )

    assert pipeline.planned.use_multi_ticker_briefs is True
    assert sorted(pipeline.per_ticker_reranked.keys()) == ["GOOGL", "NVDA"]
    assert sorted(pipeline.per_ticker_briefs.keys()) == ["GOOGL", "NVDA"]
    assert retriever.retrieve_calls == 2

    response = service.response_from_pipeline(pipeline=pipeline, settings=settings)
    assert response.status == QueryStatus.ANSWERED
    assert len(llm.chat_calls) >= 4


def test_tools_only_plan_falls_back_to_rag_when_tools_have_no_actionable_data() -> None:
    finance_tools = FakeFinanceTools(status=FinanceToolStatus.NO_DATA, summary="No metrics available.", payload=None)
    service, retriever, _llm = build_service(
        finance_tools,
        planner_outputs=[
            PlannerDecision(
                action=PlannerAction.ANSWER,
                tickers=["AAPL"],
                use_rag=False,
                use_yfinance=True,
                use_edgar_financials=False,
            )
        ],
    )

    settings = resolve_generation_settings(mode="quick")
    pipeline = service.execute_query_pipeline(question="What is AAPL market cap right now?", settings=settings)

    assert pipeline.planned.status == QueryStatus.ANSWERED
    assert pipeline.planned.use_rag is False
    assert finance_tools.calls == 1
    assert retriever.retrieve_calls == 1
    assert any(event.tool == "rag_function_fallback" for event in pipeline.tool_trace)


def test_planner_invalid_json_triggers_repair_call() -> None:
    finance_tools = FakeFinanceTools()
    service, _retriever, llm = build_service(
        finance_tools,
        planner_outputs=[
            "definitely not valid planner json",
            PlannerDecision(
                action=PlannerAction.ANSWER,
                tickers=["AAPL"],
                characteristics=[QueryCharacteristic.MARKET_DATA],
                use_rag=False,
                use_yfinance=True,
                use_edgar_financials=False,
            ),
        ],
    )

    decision = service._planner_decision_from_llm(
        question="What is AAPL market cap?",
        companies=service.list_ingested_companies(),
        explicit_tickers=["AAPL"],
        filing_date_from=None,
        filing_date_to=None,
    )

    assert decision is not None
    assert decision.action == PlannerAction.ANSWER
    assert decision.tickers == ["AAPL"]
    assert len(llm.chat_calls) == 2
    assert "You repair malformed planner outputs" in llm.chat_calls[1]["messages"][0]["content"]


def test_planner_error_triggers_repair_call() -> None:
    finance_tools = FakeFinanceTools()
    service, _retriever, llm = build_service(
        finance_tools,
        planner_outputs=[
            RuntimeError("planner endpoint timeout"),
            PlannerDecision(
                action=PlannerAction.ANSWER,
                tickers=["AAPL"],
                characteristics=[QueryCharacteristic.FINANCIAL_METRICS, QueryCharacteristic.PERIOD_SCOPED],
                use_rag=False,
                use_yfinance=False,
                use_edgar_financials=True,
            ),
        ],
    )

    decision = service._planner_decision_from_llm(
        question="What was AAPL net income in 2025?",
        companies=service.list_ingested_companies(),
        explicit_tickers=["AAPL"],
        filing_date_from=None,
        filing_date_to=None,
    )

    assert decision is not None
    assert decision.use_edgar_financials is True
    assert len(llm.chat_calls) == 2
    assert "You repair malformed planner outputs" in llm.chat_calls[1]["messages"][0]["content"]


def test_plan_query_uses_heuristics_only_after_planner_and_repair_failure() -> None:
    finance_tools = FakeFinanceTools()
    service, retriever, _llm = build_service(finance_tools, planner_outputs=["not-json", "still-not-json"])

    planned = service.plan_query(
        question="What was AAPL net income in 2025?", tickers=["AAPL"], filing_date_from=None, filing_date_to=None
    )

    assert planned.status == QueryStatus.ANSWERED
    assert planned.tickers == ["AAPL"]
    assert planned.filters is not None
    assert retriever.last_filing_date_from == "2025-01-01"
    assert retriever.last_filing_date_to == "2025-12-31"
    fallback_events = [event for event in planned.tool_trace if event.tool == "planner_fallback"]
    assert len(fallback_events) == 1


def test_planner_characteristics_route_tools_first_without_rag() -> None:
    finance_tools = FakeFinanceTools()
    service, retriever, _llm = build_service(
        finance_tools,
        planner_outputs=[
            PlannerDecision(
                action=PlannerAction.ANSWER,
                tickers=["AAPL"],
                characteristics=[QueryCharacteristic.MARKET_DATA, QueryCharacteristic.SIMPLE_NUMERIC],
                use_rag=None,
                use_yfinance=None,
                use_edgar_financials=None,
            )
        ],
    )

    settings = resolve_generation_settings(mode="quick")
    pipeline = service.execute_query_pipeline(question="What is AAPL market cap right now?", settings=settings)

    assert pipeline.planned.use_rag is False
    assert pipeline.planned.use_yfinance is True
    assert pipeline.planned.use_edgar_financials is False
    assert retriever.retrieve_calls == 0


def test_planner_characteristics_route_rag_for_narrative() -> None:
    finance_tools = FakeFinanceTools()
    service, retriever, _llm = build_service(
        finance_tools,
        planner_outputs=[
            PlannerDecision(
                action=PlannerAction.ANSWER,
                tickers=["AAPL"],
                characteristics=[QueryCharacteristic.FILING_NARRATIVE],
                use_rag=None,
                use_yfinance=None,
                use_edgar_financials=None,
            )
        ],
    )

    settings = resolve_generation_settings(mode="quick")
    pipeline = service.execute_query_pipeline(
        question="Based on AAPL filings, summarize strategy and risk factors.", settings=settings
    )

    assert pipeline.planned.use_rag is True
    assert pipeline.planned.use_yfinance is False
    assert pipeline.planned.use_edgar_financials is False
    assert finance_tools.calls == 0
    assert retriever.retrieve_calls == 1


def test_planner_mixed_characteristics_use_tools_and_rag() -> None:
    finance_tools = FakeFinanceTools()
    service, retriever, _llm = build_service(
        finance_tools,
        planner_outputs=[
            PlannerDecision(
                action=PlannerAction.ANSWER,
                tickers=["AAPL"],
                characteristics=[QueryCharacteristic.FILING_NARRATIVE, QueryCharacteristic.MARKET_DATA],
                use_rag=None,
                use_yfinance=None,
                use_edgar_financials=None,
            )
        ],
    )

    settings = resolve_generation_settings(mode="quick")
    pipeline = service.execute_query_pipeline(
        question="Explain AAPL strategy from filings and include current valuation context.", settings=settings
    )

    assert pipeline.planned.use_rag is True
    assert pipeline.planned.use_yfinance is True
    assert finance_tools.calls == 1
    assert retriever.retrieve_calls == 1


def test_period_scoped_financial_metrics_stay_tools_first_when_non_narrative() -> None:
    finance_tools = FakeFinanceTools()
    service, retriever, _llm = build_service(
        finance_tools,
        planner_outputs=[
            PlannerDecision(
                action=PlannerAction.ANSWER,
                tickers=["AAPL"],
                characteristics=[QueryCharacteristic.FINANCIAL_METRICS, QueryCharacteristic.PERIOD_SCOPED],
                use_rag=None,
                use_yfinance=None,
                use_edgar_financials=None,
            )
        ],
    )

    settings = resolve_generation_settings(mode="quick")
    pipeline = service.execute_query_pipeline(question="What was AAPL net income in 2025?", settings=settings)

    assert pipeline.planned.use_rag is False
    assert pipeline.planned.use_edgar_financials is True
    assert finance_tools.calls == 1
    assert retriever.retrieve_calls == 0


def test_prompt_extra_injects_evidence_discipline() -> None:
    finance_tools = FakeFinanceTools()
    service, _retriever, llm = build_service(
        finance_tools,
        planner_outputs=[
            PlannerDecision(
                action=PlannerAction.ANSWER,
                tickers=["AAPL"],
                use_rag=True,
                use_yfinance=False,
                use_edgar_financials=False,
            )
        ],
    )

    settings = resolve_generation_settings(mode="quick", enable_refine=False)
    pipeline = service.execute_query_pipeline(
        question="Based on AAPL SEC filings in 2025, summarize strategy and key risks.", settings=settings
    )
    _ = service.response_from_pipeline(pipeline=pipeline, settings=settings)

    calls = generation_calls(llm)
    assert len(calls) == 1
    assert "Evidence discipline mode" in calls[0]["messages"][0]["content"]
    assert "If a requested point has no explicit quote support" in calls[0]["messages"][0]["content"]


def test_plan_query_fallback_infers_ticker_via_live_yfinance_search() -> None:
    finance_tools = FakeFinanceTools()
    service, _retriever, _llm = build_service(finance_tools, planner_outputs=["bad-json", "still-bad-json"])

    planned = service.plan_query(
        question="How does NVIDIA Corporation look right now as an investment?",
        tickers=None,
        filing_date_from=None,
        filing_date_to=None,
    )

    if planned.status != QueryStatus.ANSWERED:
        pytest.skip("Live yfinance search was unavailable in this environment.")

    assert "NVDA" in planned.tickers
    assert any(event.tool == "planner_fallback" for event in planned.tool_trace)
