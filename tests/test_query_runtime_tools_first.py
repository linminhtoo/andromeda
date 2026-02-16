from __future__ import annotations

from dataclasses import dataclass
from datetime import date

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


def make_scored_chunk(*, chunk_id: str, section_path: str, text: str, score: float = 1.0) -> ScoredChunk:
    return ScoredChunk(
        chunk=DocChunk(
            id=chunk_id,
            doc_id="doc-AAPL",
            text=text,
            page_no=None,
            headings=["Item 2"],
            source="aapl_10q.md",
            metadata={"retrieval_text": text, "section_path": section_path, "doc": {"ticker": "AAPL"}},
        ),
        score=score,
        source="hybrid",
    )


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


def test_finance_tools_can_be_disabled_by_env(monkeypatch) -> None:
    finance_tools = FakeFinanceTools()
    service, retriever, _llm = build_service(finance_tools)
    monkeypatch.setenv("FINRAG_DISABLE_FINANCE_TOOLS", "1")

    monkeypatch.setattr(
        service,
        "_planner_decision_from_llm",
        lambda **_kwargs: PlannerDecision(
            action=PlannerAction.ANSWER, tickers=["AAPL"], use_rag=True, use_yfinance=True, use_edgar_financials=True
        ),
    )

    settings = resolve_generation_settings(mode="quick")
    pipeline = service.execute_query_pipeline(question="What was AAPL revenue in the latest filing?", settings=settings)

    assert pipeline.planned.status == QueryStatus.ANSWERED
    assert finance_tools.calls == 0
    assert retriever.retrieve_calls == 1
    assert any(event.tool == "finance_tools_skip" for event in pipeline.tool_trace)


def test_multi_ticker_briefs_path_generates_parallel_briefs(monkeypatch) -> None:
    finance_tools = FakeFinanceTools()
    service, retriever, llm = build_service(finance_tools)

    monkeypatch.setattr(
        service,
        "_planner_decision_from_llm",
        lambda **_kwargs: PlannerDecision(
            action=PlannerAction.ANSWER,
            tickers=["NVDA", "GOOGL"],
            use_rag=True,
            use_yfinance=False,
            use_edgar_financials=False,
            use_per_ticker_retrieval=True,
            use_multi_ticker_briefs=True,
        ),
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
    assert len(llm.chat_calls) >= 3


def test_question_year_infers_retrieval_date_window(monkeypatch) -> None:
    finance_tools = FakeFinanceTools()
    service, retriever, _llm = build_service(finance_tools)

    monkeypatch.setattr(
        service,
        "_planner_decision_from_llm",
        lambda **_kwargs: PlannerDecision(
            action=PlannerAction.ANSWER, tickers=["AAPL"], use_rag=True, use_yfinance=False, use_edgar_financials=False
        ),
    )

    settings = resolve_generation_settings(mode="quick")
    pipeline = service.execute_query_pipeline(
        question="Based on AAPL filings in 2025, summarize strategy and risks.", settings=settings
    )

    assert pipeline.planned.status == QueryStatus.ANSWERED
    assert pipeline.planned.filters is not None
    assert retriever.last_filing_date_from == "2025-01-01"
    assert retriever.last_filing_date_to == "2025-12-31"
    assert pipeline.planned.filters.filing_date_from is not None
    assert pipeline.planned.filters.filing_date_from.isoformat() == "2025-01-01"
    assert pipeline.planned.filters.filing_date_to is not None
    assert pipeline.planned.filters.filing_date_to.isoformat() == "2025-12-31"
    assert any(event.tool == "infer_question_date_window" for event in pipeline.tool_trace)


def test_narrative_sec_question_forces_rag_and_disables_tools(monkeypatch) -> None:
    finance_tools = FakeFinanceTools()
    service, retriever, _llm = build_service(finance_tools)

    monkeypatch.setattr(
        service,
        "_planner_decision_from_llm",
        lambda **_kwargs: PlannerDecision(
            action=PlannerAction.ANSWER, tickers=["AAPL"], use_rag=False, use_yfinance=True, use_edgar_financials=True
        ),
    )

    settings = resolve_generation_settings(mode="quick")
    pipeline = service.execute_query_pipeline(
        question="Based on AAPL SEC filings in 2025, summarize strategy and key risks.", settings=settings
    )

    assert pipeline.planned.status == QueryStatus.ANSWERED
    assert pipeline.planned.use_rag is True
    assert pipeline.planned.use_yfinance is False
    assert pipeline.planned.use_edgar_financials is False
    assert finance_tools.calls == 0
    assert retriever.retrieve_calls >= 1


def test_narrative_refine_runs_faithfulness_scrub_pass(monkeypatch) -> None:
    finance_tools = FakeFinanceTools()
    service, _retriever, llm = build_service(finance_tools)

    monkeypatch.setattr(
        service,
        "_planner_decision_from_llm",
        lambda **_kwargs: PlannerDecision(
            action=PlannerAction.ANSWER, tickers=["AAPL"], use_rag=True, use_yfinance=False, use_edgar_financials=False
        ),
    )

    settings = resolve_generation_settings(mode="normal", enable_refine=True)
    pipeline = service.execute_query_pipeline(
        question="Based on AAPL SEC filings in 2025, summarize strategy and key risks.", settings=settings
    )
    _ = service.response_from_pipeline(pipeline=pipeline, settings=settings)

    assert len(llm.chat_calls) == 3
    assert any("Candidate answer:" in call["messages"][1]["content"] for call in llm.chat_calls)


def test_narrative_question_injects_prompt_extra_guidance(monkeypatch) -> None:
    finance_tools = FakeFinanceTools()
    service, _retriever, llm = build_service(finance_tools)

    monkeypatch.setattr(
        service,
        "_planner_decision_from_llm",
        lambda **_kwargs: PlannerDecision(
            action=PlannerAction.ANSWER, tickers=["AAPL"], use_rag=True, use_yfinance=False, use_edgar_financials=False
        ),
    )

    settings = resolve_generation_settings(mode="quick", enable_refine=False)
    pipeline = service.execute_query_pipeline(
        question="Based on AAPL SEC filings in 2025, summarize strategy and key risks.", settings=settings
    )
    _ = service.response_from_pipeline(pipeline=pipeline, settings=settings)

    assert len(llm.chat_calls) == 1
    assert "Narrative evidence mode" in llm.chat_calls[0]["messages"][0]["content"]
    assert "If a requested point has no explicit quote support" in llm.chat_calls[0]["messages"][0]["content"]


def test_context_coverage_prompt_extra_flags_missing_growth() -> None:
    finance_tools = FakeFinanceTools()
    service, _retriever, _llm = build_service(finance_tools)

    risk_only = make_scored_chunk(
        chunk_id="risk-only",
        section_path="PART II > ITEM 1A. RISK FACTORS",
        text="Regulatory and cybersecurity risks may adversely affect the business.",
    )
    extra = service.context_coverage_prompt_extra(
        question="Based on AAPL filings, what are key growth drivers and risks?", reranked=[risk_only]
    )

    assert extra is not None
    assert "does not contain explicit growth/strategy evidence" in extra


def test_narrative_aspect_coverage_adds_growth_chunk_when_question_needs_growth_and_risk() -> None:
    finance_tools = FakeFinanceTools()
    service, _retriever, _llm = build_service(finance_tools)
    risk_a = make_scored_chunk(
        chunk_id="risk-a",
        section_path="PART II > ITEM 1A. RISK FACTORS",
        text="Regulatory risks could adversely affect results.",
        score=2.0,
    )
    risk_b = make_scored_chunk(
        chunk_id="risk-b",
        section_path="PART II > ITEM 1A. RISK FACTORS",
        text="Cybersecurity risks remain elevated.",
        score=1.8,
    )
    growth = make_scored_chunk(
        chunk_id="growth-a",
        section_path="PART I > ITEM 2. RESULTS OF OPERATIONS > REVENUE",
        text="Revenue growth was driven by cloud demand and enterprise expansion.",
        score=1.0,
    )

    out = service._enforce_narrative_aspect_coverage(
        question="Based on AAPL filings, what are key growth drivers and key risks?",
        primary=[risk_a, risk_b],
        fallback=[risk_a, risk_b, growth],
        limit=3,
    )

    out_ids = {item.chunk.id for item in out}
    assert "growth-a" in out_ids
    assert "risk-a" in out_ids or "risk-b" in out_ids


def test_narrative_retrieval_queries_expand_growth_and_risk() -> None:
    finance_tools = FakeFinanceTools()
    service, _retriever, _llm = build_service(finance_tools)

    queries = service.narrative_retrieval_queries(
        "Based on AAPL filings in 2025, what are key growth drivers and key risks?"
    )
    assert len(queries) == 3
    assert "growth drivers" in queries[1].lower() or "strategy" in queries[1].lower()
    assert "risk factors" in queries[2].lower()


def test_apply_mmr_diversity_prefers_diverse_chunks() -> None:
    finance_tools = FakeFinanceTools()
    service, _retriever, _llm = build_service(finance_tools)

    risk_a = make_scored_chunk(
        chunk_id="risk-a",
        section_path="PART II > ITEM 1A. RISK FACTORS",
        text="Regulatory risk factors include antitrust privacy and cybersecurity penalties.",
        score=3.0,
    )
    risk_b = make_scored_chunk(
        chunk_id="risk-b",
        section_path="PART II > ITEM 1A. RISK FACTORS",
        text="Regulatory risk factors include antitrust privacy and cybersecurity fines.",
        score=2.8,
    )
    growth = make_scored_chunk(
        chunk_id="growth-a",
        section_path="PART I > ITEM 2. RESULTS OF OPERATIONS > REVENUE",
        text="Revenue expansion was driven by cloud adoption and enterprise demand.",
        score=2.9,
    )

    out = service.apply_mmr_diversity(candidates=[risk_a, risk_b, growth], limit=2, lambda_mult=0.78)
    out_ids = {item.chunk.id for item in out}

    assert "risk-a" in out_ids
    assert "growth-a" in out_ids


def test_mmr_diversity_flag_defaults_off(monkeypatch) -> None:
    finance_tools = FakeFinanceTools()
    service, _retriever, _llm = build_service(finance_tools)

    monkeypatch.delenv("FINRAG_ENABLE_MMR_DIVERSITY", raising=False)
    assert service.mmr_diversity_enabled() is False

    monkeypatch.setenv("FINRAG_ENABLE_MMR_DIVERSITY", "1")
    assert service.mmr_diversity_enabled() is True


def test_simple_numeric_question_forces_tools_first(monkeypatch) -> None:
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
    pipeline = service.execute_query_pipeline(question="What is AAPL market cap right now?", settings=settings)

    assert pipeline.planned.status == QueryStatus.ANSWERED
    assert pipeline.planned.use_rag is False
    assert pipeline.planned.use_yfinance is True
    assert pipeline.planned.use_edgar_financials is False
    assert finance_tools.calls == 1
    assert retriever.retrieve_calls == 0


def test_period_scoped_numeric_question_uses_rag_for_grounding(monkeypatch) -> None:
    finance_tools = FakeFinanceTools()
    service, retriever, _llm = build_service(finance_tools)

    monkeypatch.setattr(
        service,
        "_planner_decision_from_llm",
        lambda **_kwargs: PlannerDecision(
            action=PlannerAction.ANSWER, tickers=["AAPL"], use_rag=False, use_yfinance=False, use_edgar_financials=True
        ),
    )

    settings = resolve_generation_settings(mode="quick")
    pipeline = service.execute_query_pipeline(question="What was AAPL net income in 2025?", settings=settings)

    assert pipeline.planned.status == QueryStatus.ANSWERED
    assert pipeline.planned.use_rag is True
    assert pipeline.planned.use_edgar_financials is True
    assert finance_tools.calls == 1
    assert retriever.retrieve_calls == 1


def test_tools_only_plan_falls_back_to_rag_when_tools_have_no_actionable_data(monkeypatch) -> None:
    finance_tools = FakeFinanceTools(status=FinanceToolStatus.NO_DATA, summary="No metrics available.", payload=None)
    service, retriever, _llm = build_service(finance_tools)

    monkeypatch.setattr(
        service,
        "_planner_decision_from_llm",
        lambda **_kwargs: PlannerDecision(
            action=PlannerAction.ANSWER, tickers=["AAPL"], use_rag=False, use_yfinance=True, use_edgar_financials=False
        ),
    )

    settings = resolve_generation_settings(mode="quick")
    pipeline = service.execute_query_pipeline(question="What is AAPL market cap right now?", settings=settings)

    assert pipeline.planned.status == QueryStatus.ANSWERED
    assert pipeline.planned.use_rag is False
    assert finance_tools.calls == 1
    assert retriever.retrieve_calls == 1
    assert any(event.tool == "rag_function_fallback" for event in pipeline.tool_trace)
