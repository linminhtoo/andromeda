from __future__ import annotations

from dataclasses import dataclass

from finrag.dataclasses import DocChunk, ScoredChunk
from finrag.db import IngestedCompanyRow, RetrievalFilters
from finrag.finance_tools import FinanceToolResult, FinanceToolStatus
from finrag.generation_controls import resolve_generation_settings
from finrag.query_runtime import PlannerAction, PlannerDecision, QueryStatus, RAGService
from tests.fakes import RecordingLLM


class FakeRetriever:
    retrieval_text_key = "retrieval_text"

    def __init__(self) -> None:
        self.retrieve_calls = 0

    def list_ingested_companies(self) -> list[IngestedCompanyRow]:
        return [IngestedCompanyRow(ticker="AAPL", company="Apple Inc.")]

    def build_filters(
        self, *, tickers: list[str] | None, filing_date_from: str | None, filing_date_to: str | None
    ) -> RetrievalFilters:
        _ = filing_date_from, filing_date_to
        if tickers is None:
            return RetrievalFilters()
        return RetrievalFilters(tickers=tuple(tickers))

    def retrieve_hybrid(
        self, _question: str, *, top_k_semantic: int, top_k_bm25: int, top_k_final: int, filters: RetrievalFilters
    ) -> list[ScoredChunk]:
        _ = top_k_semantic, top_k_bm25, top_k_final, filters
        self.retrieve_calls += 1
        return [
            ScoredChunk(
                chunk=DocChunk(
                    id="chunk-1",
                    doc_id="doc-1",
                    text="Revenue grew 20% in 2025.",
                    page_no=None,
                    headings=["Item 7"],
                    source="aapl_10k.md",
                    metadata={"retrieval_text": "Revenue grew 20% in 2025.", "doc": {"ticker": "AAPL"}},
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

    def fetch_for_plan(
        self, *, question: str, tickers: list[str], use_yfinance: bool, use_edgar_financials: bool
    ) -> list[FinanceToolResult]:
        _ = question, use_yfinance, use_edgar_financials
        self.calls += 1
        return [
            FinanceToolResult(
                tool="yfinance_get_ticker_info",
                ticker=tickers[0] if tickers else None,
                status=FinanceToolStatus.OK,
                summary="Fetched snapshot.",
                payload={"market": {"currentPrice": 210.0}},
            )
        ]

    def tool_context_text(self, results: list[FinanceToolResult], *, max_chars: int = 14_000) -> str:
        _ = max_chars
        if not results:
            return ""
        return "TOOL CONTEXT"


def build_service(finance_tools: FakeFinanceTools) -> tuple[RAGService, FakeRetriever, RecordingLLM]:
    llm = RecordingLLM(chat_fn=lambda _messages, _temperature, _response_model: "answer")
    retriever = FakeRetriever()
    service = RAGService(
        llm=llm,
        retriever=retriever,
        reranker=FakeReranker(),
        context_key="retrieval_context",
        finance_tools=finance_tools,
    )
    return service, retriever, llm


def test_tools_only_plan_skips_rag_and_still_answers(monkeypatch) -> None:
    finance_tools = FakeFinanceTools()
    service, retriever, llm = build_service(finance_tools)

    monkeypatch.setattr(
        service,
        "_planner_decision_from_llm",
        lambda **_kwargs: PlannerDecision(
            action=PlannerAction.ANSWER, tickers=["AAPL"], use_rag=False, use_yfinance=True, use_edgar_financials=True
        ),
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

    prompt_messages = llm.chat_calls[0]["messages"]
    assert "Tool Context:\nTOOL CONTEXT" in prompt_messages[1]["content"]


def test_tools_plus_rag_runs_retrieval(monkeypatch) -> None:
    finance_tools = FakeFinanceTools()
    service, retriever, _llm = build_service(finance_tools)

    monkeypatch.setattr(
        service,
        "_planner_decision_from_llm",
        lambda **_kwargs: PlannerDecision(
            action=PlannerAction.ANSWER, tickers=["AAPL"], use_rag=True, use_yfinance=True, use_edgar_financials=False
        ),
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
