from __future__ import annotations

import asyncio
import json
import re
import threading
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, cast

from fastapi import Request
from pydantic import BaseModel, Field, ValidationError

from finrag.dataclasses import ScoredChunk, TopChunk
from finrag.db import RetrievalFilters
from finrag.finance_tools import FinanceToolResult, FinanceToolStatus, FinanceTools
from finrag.generation_controls import GenerationSettings
from finrag.ingestion_jobs import normalize_ticker
from finrag.llm_clients import ChatMessage, LLMClient
from finrag.metadata_models import chunk_metadata_from_value
from finrag.qa import build_draft_prompt, build_refine_prompt
from finrag.retriever import CrossEncoderReranker, PostgresHybridRetriever
from finrag.streaming import TextDeltaBatcher, iter_chat_deltas, ndjson_bytes


class QueryStatus(str, Enum):
    ANSWERED = "answered"
    CLARIFICATION_REQUIRED = "clarification_required"
    REFUSED = "refused"


class PlannerAction(str, Enum):
    ANSWER = "answer"
    CLARIFICATION_REQUIRED = "clarification_required"
    REFUSED = "refused"


class QueryRequest(BaseModel):
    question: str
    mode: str | None = None
    conversation_id: str | None = None

    tickers: list[str] | None = None
    filing_date_from: str | None = None
    filing_date_to: str | None = None

    top_k_retrieve: int | None = None
    top_k_rerank: int | None = None
    draft_max_tokens: int | None = None
    final_max_tokens: int | None = None
    enable_rerank: bool | None = None
    enable_refine: bool | None = None


class QueryStreamRequest(QueryRequest):
    request_id: str | None = None


class ToolTraceEvent(BaseModel):
    tool: str
    args: dict[str, object] = Field(default_factory=dict)
    result: str


class FinanceToolResultPayload(BaseModel):
    tool: str
    ticker: str | None = None
    status: FinanceToolStatus
    summary: str
    payload: object | None = None


class QueryResponse(BaseModel):
    status: QueryStatus = QueryStatus.ANSWERED
    conversation_id: str | None = None
    clarifying_question: str | None = None
    tool_trace: list[ToolTraceEvent] = Field(default_factory=list)
    tool_results: list[FinanceToolResultPayload] = Field(default_factory=list)
    draft_answer: str
    final_answer: str
    top_chunks: list[TopChunk]
    retrieved_chunks: list[TopChunk] | None = None


@dataclass
class StreamStageResult:
    """
    Mutable state container for one streamed generation stage.
    """

    text: str = ""
    step_ms: float = 0.0


async def stream_text_stage(
    *,
    llm: LLMClient,
    request: Request,
    cancel_evt: threading.Event,
    prompt: list[ChatMessage],
    temperature: float,
    delta_type: str,
    allow_stream: bool,
    result: StreamStageResult,
) -> AsyncIterator[bytes]:
    """
    Stream or batch-generate one model stage and emit NDJSON text deltas.
    """

    full_text = ""
    t0 = time.monotonic()

    def is_cancelled() -> bool:
        return cancel_evt.is_set()

    def set_cancelled() -> None:
        cancel_evt.set()

    if allow_stream:
        stream_messages = cast(list[dict[str, Any]], prompt)
        batcher = TextDeltaBatcher.from_env()
        async for delta in iter_chat_deltas(
            llm,
            stream_messages,
            temperature=temperature,
            is_cancelled=is_cancelled,
            set_cancelled=set_cancelled,
            is_disconnected=request.is_disconnected,
        ):
            full_text += delta
            batcher.add(delta)
            out = batcher.pop_ready()
            if out:
                yield ndjson_bytes({"type": delta_type, "delta": out})
            if is_cancelled():
                break
        out = batcher.pop_all()
        if out:
            yield ndjson_bytes({"type": delta_type, "delta": out})
    else:
        full_text = await asyncio.to_thread(llm.chat, prompt, temperature)

    result.text = full_text
    result.step_ms = (time.monotonic() - t0) * 1000.0


class PlannerDecision(BaseModel):
    action: PlannerAction = PlannerAction.ANSWER
    tickers: list[str] = Field(default_factory=list)
    filing_date_from: str | None = None
    filing_date_to: str | None = None
    clarifying_question: str | None = None
    refusal_reason: str | None = None
    use_per_ticker_retrieval: bool | None = None
    use_rag: bool | None = None
    use_yfinance: bool | None = None
    use_edgar_financials: bool | None = None


@dataclass
class PlannedQuery:
    status: QueryStatus
    question: str
    filters: RetrievalFilters | None
    tickers: list[str]
    clarifying_question: str | None = None
    refusal_message: str | None = None
    use_per_ticker_retrieval: bool = False
    use_rag: bool = True
    use_yfinance: bool = False
    use_edgar_financials: bool = False
    tool_trace: list[ToolTraceEvent] = field(default_factory=list)


@dataclass
class QueryPipelineExecution:
    question: str
    planned: PlannedQuery
    tool_trace: list[ToolTraceEvent] = field(default_factory=list)
    tool_results: list[FinanceToolResult] = field(default_factory=list)
    hybrid: list[ScoredChunk] = field(default_factory=list)
    reranked: list[ScoredChunk] = field(default_factory=list)
    plan_step_ms: float | None = None
    tools_step_ms: float | None = None
    retrieve_step_ms: float | None = None
    rerank_step_ms: float | None = None


class RAGService:
    """
    Query orchestration runtime for tools-first answer generation.
    """

    def __init__(
        self,
        *,
        llm: LLMClient,
        retriever: PostgresHybridRetriever,
        reranker: CrossEncoderReranker,
        context_key: str,
        finance_tools: FinanceTools | None = None,
    ):
        self.llm = llm
        self.retriever = retriever
        self.reranker = reranker
        self._context_key = context_key
        self.finance_tools = finance_tools if finance_tools is not None else FinanceTools()

    @staticmethod
    def _tool_event(tool: str, *, args: dict[str, object] | None = None, result: str) -> ToolTraceEvent:
        return ToolTraceEvent(tool=tool, args=(args or {}), result=result)

    @staticmethod
    def _chunk_metadata_for_ui(meta: object) -> dict | None:
        parsed = chunk_metadata_from_value(meta)
        out: dict[str, object] = {}

        if parsed.doc is not None:
            keep = {}
            if parsed.doc.company is not None:
                keep["company"] = parsed.doc.company
            if parsed.doc.ticker is not None:
                keep["ticker"] = parsed.doc.ticker
            if parsed.doc.cik is not None:
                keep["cik"] = parsed.doc.cik
            if parsed.doc.filing_type is not None:
                keep["filing_type"] = parsed.doc.filing_type
            if parsed.doc.filing_date is not None:
                keep["filing_date"] = parsed.doc.filing_date
            if parsed.doc.period_end_date is not None:
                keep["period_end_date"] = parsed.doc.period_end_date
            if parsed.doc.filing_quarter is not None:
                keep["filing_quarter"] = parsed.doc.filing_quarter
            if parsed.doc.filing_quarter_basis is not None:
                keep["filing_quarter_basis"] = parsed.doc.filing_quarter_basis
            if keep:
                out["doc"] = keep

        if parsed.summary is not None and parsed.summary.strip():
            out["summary"] = parsed.summary.strip()

        line_start_raw = parsed.extra["line_start"] if "line_start" in parsed.extra else None
        if isinstance(line_start_raw, int) and line_start_raw > 0:
            out["line_start"] = line_start_raw

        line_end_raw = parsed.extra["line_end"] if "line_end" in parsed.extra else None
        if isinstance(line_end_raw, int) and line_end_raw > 0:
            out["line_end"] = line_end_raw

        return out or None

    def _serialize_top_chunks(self, reranked: list[ScoredChunk]) -> list[TopChunk]:
        retrieval_text_key = getattr(self.retriever, "retrieval_text_key", "retrieval_text")
        out: list[TopChunk] = []
        for sc in reranked:
            parsed = chunk_metadata_from_value(sc.chunk.metadata)
            if retrieval_text_key == "retrieval_text":
                raw_text = parsed.retrieval_text
            else:
                raw_text = parsed.context_for_key(retrieval_text_key)
            display_text = str(raw_text or sc.chunk.text or "")
            source_text = str(sc.chunk.text or "")
            context_value = parsed.context_for_key(self._context_key)
            out.append(
                TopChunk(
                    chunk_id=sc.chunk.id,
                    doc_id=sc.chunk.doc_id,
                    page_no=sc.chunk.page_no,
                    headings=sc.chunk.headings,
                    score=sc.score,
                    preview=display_text[:300],
                    source=sc.chunk.source,
                    text=display_text,
                    source_text=source_text,
                    context=context_value,
                    metadata=self._chunk_metadata_for_ui(parsed.to_dict()),
                )
            )
        return out

    @staticmethod
    def serialize_finance_tool_results(results: list[FinanceToolResult]) -> list[FinanceToolResultPayload]:
        """
        Convert internal finance tool results to API payload models.
        """

        out: list[FinanceToolResultPayload] = []
        for item in results:
            out.append(
                FinanceToolResultPayload(
                    tool=item.tool, ticker=item.ticker, status=item.status, summary=item.summary, payload=item.payload
                )
            )
        return out

    def list_ingested_companies(self) -> list[dict[str, str]]:
        """
        Return indexed ticker/company pairs from PostgreSQL metadata.
        """

        rows = self.retriever.list_ingested_companies()
        out: list[dict[str, str]] = []
        for row in rows:
            company = row.company.strip() if isinstance(row.company, str) and row.company.strip() else row.ticker
            out.append({"ticker": row.ticker.strip().upper(), "company": company})
        return out

    @staticmethod
    def _normalize_ticker_list(tickers: list[str] | None) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for raw in tickers or []:
            text = str(raw or "").strip()
            if not text:
                continue
            try:
                normalized = normalize_ticker(text)
            except ValueError:
                normalized = text.upper()
            if normalized in seen:
                continue
            seen.add(normalized)
            out.append(normalized)
        return out

    @staticmethod
    def _extract_json_object(raw: str) -> dict[str, object] | None:
        text = str(raw or "").strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            pass

        fenced = text.strip()
        if fenced.startswith("```"):
            fenced = fenced.strip("`")
            if "\n" in fenced:
                fenced = fenced.split("\n", 1)[1]
            fenced = fenced.strip()
        start = fenced.find("{")
        end = fenced.rfind("}")
        if start < 0 or end < 0 or end <= start:
            return None
        candidate = fenced[start : end + 1]
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            return None
        if not isinstance(parsed, dict):
            return None
        return parsed

    @staticmethod
    def _normalize_plan_action(action: PlannerAction) -> QueryStatus:
        if action == PlannerAction.ANSWER:
            return QueryStatus.ANSWERED
        if action == PlannerAction.CLARIFICATION_REQUIRED:
            return QueryStatus.CLARIFICATION_REQUIRED
        if action == PlannerAction.REFUSED:
            return QueryStatus.REFUSED
        return QueryStatus.ANSWERED

    @staticmethod
    def _question_mentions_comparison(question: str) -> bool:
        lowered = question.lower()
        tokens = (" compare ", " versus ", " vs ", " relative to ", " better investment ", " which is better ", " or ")
        padded = f" {lowered} "
        return any(token in padded for token in tokens)

    @staticmethod
    def _question_mentions_market_data(question: str) -> bool:
        lowered = f" {question.lower()} "
        tokens = (
            " stock price ",
            " price ",
            " chart ",
            " valuation ",
            " market cap ",
            " news ",
            " return ",
            " performance ",
            " volume ",
            " pe ratio ",
            " p/e ",
            " dividend ",
        )
        return any(token in lowered for token in tokens)

    @staticmethod
    def _question_mentions_financial_metrics(question: str) -> bool:
        lowered = f" {question.lower()} "
        tokens = (
            " revenue ",
            " net income ",
            " gross margin ",
            " operating margin ",
            " eps ",
            " balance sheet ",
            " cash flow ",
            " free cash flow ",
            " assets ",
            " liabilities ",
            " equity ",
            " ratio ",
            " debt ",
        )
        return any(token in lowered for token in tokens)

    @staticmethod
    def _question_mentions_filing_narrative(question: str) -> bool:
        lowered = f" {question.lower()} "
        tokens = (
            " risk factor ",
            " management discussion ",
            " md&a ",
            " discuss ",
            " explain ",
            " guidance ",
            " outlook ",
            " strategy ",
            " segment ",
            " why ",
        )
        return any(token in lowered for token in tokens)

    def resolve_tool_usage_from_decision(self, *, question: str, decision: PlannerDecision) -> tuple[bool, bool, bool]:
        """
        Resolve planner tool flags into effective `use_rag`, `use_yfinance`, and `use_edgar_financials`.
        """

        use_yfinance = (
            bool(decision.use_yfinance)
            if decision.use_yfinance is not None
            else self._question_mentions_market_data(question)
        )
        use_edgar_financials = (
            bool(decision.use_edgar_financials)
            if decision.use_edgar_financials is not None
            else self._question_mentions_financial_metrics(question)
        )

        if decision.use_rag is not None:
            use_rag = bool(decision.use_rag)
        else:
            narrative_query = self._question_mentions_filing_narrative(question)
            if narrative_query:
                use_rag = True
            elif use_yfinance or use_edgar_financials:
                use_rag = False
            else:
                use_rag = True

        if not use_rag and not use_yfinance and not use_edgar_financials:
            use_rag = True
        return use_rag, use_yfinance, use_edgar_financials

    def _infer_tickers_from_question(self, question: str, companies: list[dict[str, str]]) -> list[str]:
        inferred: list[str] = []
        seen: set[str] = set()
        known_tickers = {str(item["ticker"]).strip().upper() for item in companies if "ticker" in item}

        upper_question = question.upper()
        ticker_pattern = re.compile(r"\b[A-Z][A-Z0-9.-]{0,11}\b")
        for match in ticker_pattern.findall(upper_question):
            token = match.strip().upper()
            if token in known_tickers and token not in seen:
                seen.add(token)
                inferred.append(token)

        lowered_question = " " + re.sub(r"[^a-z0-9]+", " ", question.lower()).strip() + " "
        for item in companies:
            ticker = str(item["ticker"]).strip().upper()
            company = str(item["company"]).strip()
            if not ticker or not company:
                continue
            normalized_company = " " + re.sub(r"[^a-z0-9]+", " ", company.lower()).strip() + " "
            if normalized_company.strip() and normalized_company in lowered_question and ticker not in seen:
                seen.add(ticker)
                inferred.append(ticker)

        return inferred

    @staticmethod
    def default_clarifying_question() -> str:
        return (
            "Please clarify which ticker symbols you want analyzed. "
            "If this is a comparison question, include every ticker explicitly."
        )

    def _planner_prompt(
        self,
        *,
        question: str,
        companies: list[dict[str, str]],
        explicit_tickers: list[str],
        filing_date_from: str | None,
        filing_date_to: str | None,
    ) -> list[ChatMessage]:
        preview_limit = 250
        preview_rows = companies[:preview_limit]
        catalog_lines = [f"- {row['ticker']}: {row['company']}" for row in preview_rows]
        catalog = "\n".join(catalog_lines) if catalog_lines else "- (none)"
        explicit = ", ".join(explicit_tickers) if explicit_tickers else "(none)"
        date_from = filing_date_from or "(none)"
        date_to = filing_date_to or "(none)"

        return [
            {
                "role": "system",
                "content": (
                    "You are a retrieval planner for a financial RAG system.\n"
                    "Decide the next action before retrieval. Actions: answer, clarification_required, refused.\n"
                    "Rules:\n"
                    "1) Default to 'answer' as much as possible. This gives the greenlight to proceed with document retrieval.\n"
                    "2) If the query is too vague, choose clarification_required (USE SPARINGLY).\n"
                    "3) If the query is out-of-scope for SEC filing analysis, choose refused.\n"
                    "4) For comparisons across multiple entities, include all required tickers and set "
                    "use_per_ticker_retrieval=true.\n"
                    "5) Decide tool mix flags:\n"
                    "- use_yfinance=true for market price/news/valuation style requests.\n"
                    "- use_edgar_financials=true for direct SEC financial metric/statement requests.\n"
                    "- use_rag=true when filing narrative evidence is needed from retrieved chunks.\n"
                    "- use_rag=false for simple direct metric queries answerable from finance tools.\n"
                    "IMPORTANT: only clarify if absolutely needed. Do NOT keep asking clarifying questions."
                    "If no date range is provided, just set None for both date_from and date_to in the output - "
                    "do NOT ask for clarification on dates unless the question explicitly references time (like 'latest').\n"
                    "Return only JSON with keys:\n"
                    "action, tickers, filing_date_from, filing_date_to, clarifying_question, refusal_reason, "
                    "use_per_ticker_retrieval, use_rag, use_yfinance, use_edgar_financials."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Question:\n{question}\n\n"
                    f"Explicit request tickers: {explicit}\n"
                    f"Explicit filing_date_from: {date_from}\n"
                    f"Explicit filing_date_to: {date_to}\n\n"
                    f"Indexed ticker catalog (first {len(preview_rows)} of {len(companies)}):\n{catalog}\n"
                ),
            },
        ]

    def _planner_decision_from_llm(
        self,
        *,
        question: str,
        companies: list[dict[str, str]],
        explicit_tickers: list[str],
        filing_date_from: str | None,
        filing_date_to: str | None,
    ) -> PlannerDecision | None:
        prompt = self._planner_prompt(
            question=question,
            companies=companies,
            explicit_tickers=explicit_tickers,
            filing_date_from=filing_date_from,
            filing_date_to=filing_date_to,
        )
        try:
            raw = self.llm.chat(prompt, temperature=0.0, max_tokens=700, response_model=PlannerDecision)
        except Exception:  # noqa: BLE001
            return None
        try:
            return PlannerDecision.model_validate_json(raw)
        except ValidationError:
            payload = self._extract_json_object(raw)
            if payload is None:
                return None
            try:
                return PlannerDecision.model_validate(payload)
            except ValidationError:
                return None

    def plan_query(
        self,
        *,
        question: str,
        tickers: list[str] | None,
        filing_date_from: str | None,
        filing_date_to: str | None,
        pre_tool_trace: list[ToolTraceEvent] | None = None,
    ) -> PlannedQuery:
        """
        Plan query execution via explicit tool-style decision steps.
        """

        trace = list(pre_tool_trace or [])
        companies = self.list_ingested_companies()
        trace.append(
            self._tool_event(
                "list_ingested_companies",
                args={"count": len(companies)},
                result=f"Loaded {len(companies)} indexed tickers from PostgreSQL.",
            )
        )
        if not companies:
            msg = (
                "I can't answer yet because no indexed tickers were found in the retrieval database. "
                "Ingest at least one company first."
            )
            trace.append(self._tool_event("refuse_if_no_indexed_tickers", result=msg))
            return PlannedQuery(
                status=QueryStatus.REFUSED,
                question=question,
                filters=None,
                tickers=[],
                refusal_message=msg,
                tool_trace=trace,
            )

        explicit_tickers = self._normalize_ticker_list(tickers)
        available_set = {str(item["ticker"]).strip().upper() for item in companies}

        decision = self._planner_decision_from_llm(
            question=question,
            companies=companies,
            explicit_tickers=explicit_tickers,
            filing_date_from=filing_date_from,
            filing_date_to=filing_date_to,
        )
        if decision is None:
            # this happens when the planner LLM fails to produce valid output
            # we fall back to a simple deterministic planner that infers tickers
            # from the question and ignores date filters, but still allows refusal if no tickers can be inferred
            inferred = self._infer_tickers_from_question(question, companies)
            action = QueryStatus.ANSWERED if explicit_tickers or inferred else QueryStatus.CLARIFICATION_REQUIRED
            decision = PlannerDecision(
                action=(
                    PlannerAction.ANSWER if action == QueryStatus.ANSWERED else PlannerAction.CLARIFICATION_REQUIRED
                ),
                tickers=(explicit_tickers if explicit_tickers else inferred),
                clarifying_question=(
                    self.default_clarifying_question() if action == QueryStatus.CLARIFICATION_REQUIRED else None
                ),
                use_per_ticker_retrieval=(
                    True if len(explicit_tickers if explicit_tickers else inferred) > 1 else None
                ),
            )
            trace.append(
                self._tool_event(
                    "planner_fallback",
                    args={"inferred_tickers": list(decision.tickers)},
                    result="Planner JSON parse failed; used deterministic fallback planner.",
                )
            )
        else:
            trace.append(
                self._tool_event(
                    "planner_llm",
                    args={
                        "raw_action": decision.action.value,
                        "tickers": [str(t) for t in decision.tickers],
                        "use_rag": decision.use_rag,
                        "use_yfinance": decision.use_yfinance,
                        "use_edgar_financials": decision.use_edgar_financials,
                    },
                    result="Planner produced structured query decision.",
                )
            )

        action = self._normalize_plan_action(decision.action)
        planned_tickers = explicit_tickers or self._normalize_ticker_list(decision.tickers)
        use_rag, use_yfinance, use_edgar_financials = self.resolve_tool_usage_from_decision(
            question=question, decision=decision
        )

        if action == QueryStatus.REFUSED:
            reason = (
                decision.refusal_reason.strip()
                if isinstance(decision.refusal_reason, str) and decision.refusal_reason.strip()
                else "I can't answer this request with the current SEC filings scope."
            )
            trace.append(self._tool_event("planner_refusal", result=reason))
            return PlannedQuery(
                status=QueryStatus.REFUSED,
                question=question,
                filters=None,
                tickers=planned_tickers,
                refusal_message=reason,
                use_rag=use_rag,
                use_yfinance=use_yfinance,
                use_edgar_financials=use_edgar_financials,
                tool_trace=trace,
            )

        if not planned_tickers:
            inferred = self._infer_tickers_from_question(question, companies)
            planned_tickers = self._normalize_ticker_list(inferred)

        missing_tickers = [ticker for ticker in planned_tickers if ticker not in available_set]
        if missing_tickers:
            available_sample = ", ".join(sorted(available_set)[:20])
            reason = (
                "I can't answer because these tickers are not indexed: "
                + ", ".join(missing_tickers)
                + ". "
                + ("Indexed tickers include: " + available_sample + "." if available_sample else "")
            )
            trace.append(
                self._tool_event("validate_ticker_coverage", args={"missing_tickers": missing_tickers}, result=reason)
            )
            return PlannedQuery(
                status=QueryStatus.REFUSED,
                question=question,
                filters=None,
                tickers=planned_tickers,
                refusal_message=reason,
                use_rag=use_rag,
                use_yfinance=use_yfinance,
                use_edgar_financials=use_edgar_financials,
                tool_trace=trace,
            )

        if action == QueryStatus.CLARIFICATION_REQUIRED or not planned_tickers:
            clarifying_question = (
                decision.clarifying_question.strip()
                if isinstance(decision.clarifying_question, str) and decision.clarifying_question.strip()
                else self.default_clarifying_question()
            )
            trace.append(
                self._tool_event(
                    "request_clarification", args={"detected_tickers": planned_tickers}, result=clarifying_question
                )
            )
            return PlannedQuery(
                status=QueryStatus.CLARIFICATION_REQUIRED,
                question=question,
                filters=None,
                tickers=planned_tickers,
                clarifying_question=clarifying_question,
                use_rag=use_rag,
                use_yfinance=use_yfinance,
                use_edgar_financials=use_edgar_financials,
                tool_trace=trace,
            )

        resolved_filing_date_from = filing_date_from if filing_date_from is not None else decision.filing_date_from
        resolved_filing_date_to = filing_date_to if filing_date_to is not None else decision.filing_date_to
        filters = self.build_retrieval_filters(
            tickers=planned_tickers, filing_date_from=resolved_filing_date_from, filing_date_to=resolved_filing_date_to
        )
        use_per_ticker = (
            bool(decision.use_per_ticker_retrieval)
            if decision.use_per_ticker_retrieval is not None
            else (len(planned_tickers) > 1 or self._question_mentions_comparison(question))
        )
        trace.append(
            self._tool_event(
                "plan_tool_usage",
                args={"use_rag": use_rag, "use_yfinance": use_yfinance, "use_edgar_financials": use_edgar_financials},
                result="Resolved planner tool usage flags.",
            )
        )
        trace.append(
            self._tool_event(
                "prepare_rag_function",
                args={
                    "tickers": list(filters.normalized_tickers()),
                    "filing_date_from": (filters.filing_date_from.isoformat() if filters.filing_date_from else None),
                    "filing_date_to": (filters.filing_date_to.isoformat() if filters.filing_date_to else None),
                    "use_per_ticker_retrieval": use_per_ticker,
                },
                result="Prepared RAG function call arguments from planner decision.",
            )
        )
        return PlannedQuery(
            status=QueryStatus.ANSWERED,
            question=question,
            filters=filters,
            tickers=planned_tickers,
            use_per_ticker_retrieval=use_per_ticker,
            use_rag=use_rag,
            use_yfinance=use_yfinance,
            use_edgar_financials=use_edgar_financials,
            tool_trace=trace,
        )

    @staticmethod
    def _chunk_ticker(sc: ScoredChunk) -> str | None:
        parsed = chunk_metadata_from_value(sc.chunk.metadata)
        if parsed.doc is None or parsed.doc.ticker is None:
            return None
        ticker = parsed.doc.ticker.strip().upper()
        return ticker if ticker else None

    @staticmethod
    def _dedupe_scored_chunks(chunks: list[ScoredChunk]) -> list[ScoredChunk]:
        by_chunk_id: dict[str, ScoredChunk] = {}
        for sc in chunks:
            chunk_id = sc.chunk.id
            existing = by_chunk_id.get(chunk_id)
            if existing is None or sc.score > existing.score:
                by_chunk_id[chunk_id] = sc
        out = list(by_chunk_id.values())
        out.sort(key=lambda item: item.score, reverse=True)
        return out

    def _enforce_ticker_coverage(
        self, *, primary: list[ScoredChunk], fallback: list[ScoredChunk], tickers: list[str], limit: int
    ) -> list[ScoredChunk]:
        selected: list[ScoredChunk] = []
        selected_ids: set[str] = set()

        def pick_from_pool(pool: list[ScoredChunk], ticker: str) -> ScoredChunk | None:
            for sc in pool:
                chunk_ticker = self._chunk_ticker(sc)
                if chunk_ticker == ticker:
                    return sc
            return None

        for ticker in tickers:
            candidate = pick_from_pool(primary, ticker)
            if candidate is None:
                candidate = pick_from_pool(fallback, ticker)
            if candidate is None:
                continue
            if candidate.chunk.id in selected_ids:
                continue
            selected_ids.add(candidate.chunk.id)
            selected.append(candidate)

        combined = self._dedupe_scored_chunks(primary + fallback)
        for sc in combined:
            if len(selected) >= limit:
                break
            if sc.chunk.id in selected_ids:
                continue
            selected_ids.add(sc.chunk.id)
            selected.append(sc)

        selected.sort(key=lambda item: item.score, reverse=True)
        return selected[:limit]

    def build_retrieval_filters(
        self, *, tickers: list[str] | None, filing_date_from: str | None, filing_date_to: str | None
    ) -> RetrievalFilters:
        """
        Build validated retrieval filters for a query request.
        """

        return self.retriever.build_filters(
            tickers=tickers, filing_date_from=filing_date_from, filing_date_to=filing_date_to
        )

    def execute_finance_tools_for_plan(
        self, *, question: str, planned: PlannedQuery
    ) -> tuple[list[FinanceToolResult], list[ToolTraceEvent]]:
        """
        Execute finance tools requested by planner for the current plan.
        """

        if not planned.tickers:
            return [], [self._tool_event("finance_tools_skip", result="Skipped finance tools (no planned tickers).")]

        if not planned.use_yfinance and not planned.use_edgar_financials:
            return [], [self._tool_event("finance_tools_skip", result="Planner disabled finance tool calls.")]

        tool_results = self.finance_tools.fetch_for_plan(
            question=question,
            tickers=planned.tickers,
            use_yfinance=planned.use_yfinance,
            use_edgar_financials=planned.use_edgar_financials,
        )
        trace = [
            self._tool_event(
                "finance_tools_execute",
                args={
                    "tickers": list(planned.tickers),
                    "use_yfinance": planned.use_yfinance,
                    "use_edgar_financials": planned.use_edgar_financials,
                    "result_count": len(tool_results),
                },
                result=f"Executed finance tools and produced {len(tool_results)} result objects.",
            )
        ]
        return tool_results, trace

    def retrieve_chunks(
        self, question: str, settings: GenerationSettings, *, filters: RetrievalFilters
    ) -> list[ScoredChunk]:
        """
        Retrieve hybrid candidates for a question.
        """

        return self.retriever.retrieve_hybrid(
            question,
            top_k_semantic=settings.top_k_retrieve,
            top_k_bm25=settings.top_k_retrieve,
            top_k_final=settings.top_k_retrieve,
            filters=filters,
        )

    def retrieve_chunks_for_plan(
        self, question: str, settings: GenerationSettings, planned: PlannedQuery
    ) -> tuple[list[ScoredChunk], list[ToolTraceEvent]]:
        """
        Retrieve chunk candidates according to a planned tools-first strategy.
        """

        if planned.filters is None:
            return [], []

        if not planned.use_per_ticker_retrieval or len(planned.tickers) <= 1:
            hybrid = self.retrieve_chunks(question, settings, filters=planned.filters)
            trace = [
                self._tool_event(
                    "retrieve_chunks",
                    args={
                        "tickers": list(planned.filters.normalized_tickers()),
                        "top_k_retrieve": settings.top_k_retrieve,
                    },
                    result=f"Retrieved {len(hybrid)} chunks.",
                )
            ]
            return hybrid, trace

        per_ticker_chunks: list[ScoredChunk] = []
        trace: list[ToolTraceEvent] = []
        for ticker in planned.tickers:
            ticker_filters = self.build_retrieval_filters(
                tickers=[ticker],
                filing_date_from=(
                    planned.filters.filing_date_from.isoformat() if planned.filters.filing_date_from else None
                ),
                filing_date_to=(planned.filters.filing_date_to.isoformat() if planned.filters.filing_date_to else None),
            )
            ticker_hybrid = self.retrieve_chunks(question, settings, filters=ticker_filters)
            per_ticker_chunks.extend(ticker_hybrid)
            trace.append(
                self._tool_event(
                    "retrieve_chunks_per_ticker",
                    args={"ticker": ticker, "top_k_retrieve": settings.top_k_retrieve},
                    result=f"Retrieved {len(ticker_hybrid)} chunks for {ticker}.",
                )
            )
        deduped = self._dedupe_scored_chunks(per_ticker_chunks)
        trace.append(
            self._tool_event(
                "merge_per_ticker_candidates",
                args={"requested_tickers": planned.tickers},
                result=f"Merged {len(per_ticker_chunks)} raw candidates into {len(deduped)} unique chunks.",
            )
        )
        return deduped, trace

    def rerank_chunks(
        self, question: str, settings: GenerationSettings, hybrid: list[ScoredChunk]
    ) -> list[ScoredChunk]:
        """
        Optionally rerank retrieved chunks according to generation settings.
        """

        if not settings.enable_rerank:
            return hybrid[: settings.top_k_rerank]
        return self.reranker.rerank(
            question, hybrid, top_k=settings.top_k_rerank, candidate_text_provider=self.retriever.text_for_rerank
        )

    def rerank_chunks_for_plan(
        self, question: str, settings: GenerationSettings, planned: PlannedQuery, hybrid: list[ScoredChunk]
    ) -> tuple[list[ScoredChunk], list[ToolTraceEvent]]:
        """
        Rerank and post-process candidates for a planned query.
        """

        reranked = self.rerank_chunks(question, settings, hybrid)
        trace: list[ToolTraceEvent] = [
            self._tool_event(
                "rerank_chunks",
                args={"enable_rerank": settings.enable_rerank, "top_k_rerank": settings.top_k_rerank},
                result=f"Produced {len(reranked)} reranked chunks.",
            )
        ]
        if planned.use_per_ticker_retrieval and len(planned.tickers) > 1:
            reranked = self._enforce_ticker_coverage(
                primary=reranked, fallback=hybrid, tickers=planned.tickers, limit=settings.top_k_rerank
            )
            trace.append(
                self._tool_event(
                    "enforce_ticker_coverage",
                    args={"tickers": planned.tickers, "top_k_rerank": settings.top_k_rerank},
                    result=f"Adjusted reranked list to {len(reranked)} chunks with ticker coverage constraints.",
                )
            )
        return reranked, trace

    def execute_query_pipeline(
        self,
        *,
        question: str,
        settings: GenerationSettings,
        tickers: list[str] | None = None,
        filing_date_from: str | None = None,
        filing_date_to: str | None = None,
        pre_tool_trace: list[ToolTraceEvent] | None = None,
    ) -> QueryPipelineExecution:
        """
        Execute plan -> retrieve -> rerank once and return stage outputs.
        """

        plan_t0 = time.perf_counter()
        planned = self.plan_query(
            question=question,
            tickers=tickers,
            filing_date_from=filing_date_from,
            filing_date_to=filing_date_to,
            pre_tool_trace=pre_tool_trace,
        )
        plan_step_ms = (time.perf_counter() - plan_t0) * 1000.0

        execution = QueryPipelineExecution(
            question=question, planned=planned, tool_trace=list(planned.tool_trace), plan_step_ms=plan_step_ms
        )
        if planned.status != QueryStatus.ANSWERED:
            return execution

        tools_t0 = time.perf_counter()
        tool_results, finance_tool_trace = self.execute_finance_tools_for_plan(question=question, planned=planned)
        execution.tools_step_ms = (time.perf_counter() - tools_t0) * 1000.0
        execution.tool_results = tool_results
        execution.tool_trace.extend(finance_tool_trace)

        if not planned.use_rag:
            execution.tool_trace.append(
                self._tool_event(
                    "rag_function_skip",
                    args={"reason": "planner_use_rag_false"},
                    result="Skipped RAG retrieval function per planner tool decision.",
                )
            )
            return execution

        retrieve_t0 = time.perf_counter()
        hybrid, retrieve_trace = self.retrieve_chunks_for_plan(question, settings, planned)
        execution.retrieve_step_ms = (time.perf_counter() - retrieve_t0) * 1000.0
        execution.hybrid = hybrid
        execution.tool_trace.extend(retrieve_trace)

        rerank_t0 = time.perf_counter()
        reranked, rerank_trace = self.rerank_chunks_for_plan(question, settings, planned, hybrid)
        execution.rerank_step_ms = (time.perf_counter() - rerank_t0) * 1000.0
        execution.reranked = reranked
        execution.tool_trace.extend(rerank_trace)
        return execution

    def draft_prompt(
        self,
        question: str,
        settings: GenerationSettings,
        reranked: list[ScoredChunk],
        tool_results: list[FinanceToolResult] | None = None,
    ) -> list[ChatMessage]:
        """
        Build the first-stage prompt used for draft generation.
        """

        tool_context = self.finance_tools.tool_context_text(tool_results or [])
        return build_draft_prompt(
            question,
            reranked,
            draft_max_tokens=settings.draft_max_tokens,
            answer_style=settings.answer_style,
            tool_context=tool_context,
        )

    def final_prompt(
        self,
        question: str,
        settings: GenerationSettings,
        reranked: list[ScoredChunk],
        *,
        draft_answer: str | None = None,
        tool_results: list[FinanceToolResult] | None = None,
    ) -> list[ChatMessage]:
        """
        Build the final-stage prompt for the current settings.
        """

        if not settings.enable_refine:
            return self.draft_prompt(question, settings, reranked, tool_results=tool_results)
        if draft_answer is None:
            raise ValueError("draft_answer is required when refinement is enabled")
        tool_context = self.finance_tools.tool_context_text(tool_results or [])
        return build_refine_prompt(
            question,
            draft_answer,
            reranked,
            final_max_tokens=settings.final_max_tokens,
            answer_style=settings.answer_style,
            tool_context=tool_context,
        )

    def generate_answers(
        self,
        question: str,
        settings: GenerationSettings,
        reranked: list[ScoredChunk],
        tool_results: list[FinanceToolResult] | None = None,
    ) -> tuple[str, str]:
        """
        Generate draft/final answers from reranked chunks.
        """

        draft = self.llm.chat(
            self.draft_prompt(question, settings, reranked, tool_results=tool_results),
            temperature=settings.draft_temperature,
        )
        if not settings.enable_refine:
            return draft, draft
        final = self.llm.chat(
            self.final_prompt(question, settings, reranked, draft_answer=draft, tool_results=tool_results),
            temperature=0.0,
        )
        return draft, final

    def build_query_response(
        self,
        *,
        status: QueryStatus = QueryStatus.ANSWERED,
        conversation_id: str | None = None,
        clarifying_question: str | None = None,
        tool_trace: list[ToolTraceEvent] | None = None,
        tool_results: list[FinanceToolResult] | None = None,
        draft_answer: str,
        final_answer: str,
        reranked: list[ScoredChunk],
        include_retrieved_chunks: bool = False,
        hybrid: list[ScoredChunk] | None = None,
    ) -> QueryResponse:
        """
        Build API response payload from generated answers and chunk state.
        """

        top_chunks = self._serialize_top_chunks(reranked)
        retrieved_chunks = (
            self._serialize_top_chunks(hybrid) if include_retrieved_chunks and hybrid is not None else None
        )
        return QueryResponse(
            status=status,
            conversation_id=conversation_id,
            clarifying_question=clarifying_question,
            tool_trace=(tool_trace or []),
            tool_results=self.serialize_finance_tool_results(tool_results or []),
            draft_answer=draft_answer,
            final_answer=final_answer,
            top_chunks=top_chunks,
            retrieved_chunks=retrieved_chunks,
        )

    def response_from_pipeline(
        self,
        *,
        pipeline: QueryPipelineExecution,
        settings: GenerationSettings,
        conversation_id: str | None = None,
        include_retrieved_chunks: bool = False,
    ) -> QueryResponse:
        """
        Build a response payload from one executed query pipeline.
        """

        if pipeline.planned.status == QueryStatus.CLARIFICATION_REQUIRED:
            clarifying_question = pipeline.planned.clarifying_question or self.default_clarifying_question()
            return self.build_query_response(
                status=QueryStatus.CLARIFICATION_REQUIRED,
                conversation_id=conversation_id,
                clarifying_question=clarifying_question,
                tool_trace=pipeline.tool_trace,
                tool_results=pipeline.tool_results,
                draft_answer=clarifying_question,
                final_answer=clarifying_question,
                reranked=[],
                include_retrieved_chunks=include_retrieved_chunks,
                hybrid=[],
            )

        if pipeline.planned.status == QueryStatus.REFUSED:
            refusal = (
                pipeline.planned.refusal_message.strip()
                if isinstance(pipeline.planned.refusal_message, str) and pipeline.planned.refusal_message.strip()
                else "I can't answer this request from the currently indexed SEC filings."
            )
            return self.build_query_response(
                status=QueryStatus.REFUSED,
                conversation_id=conversation_id,
                tool_trace=pipeline.tool_trace,
                tool_results=pipeline.tool_results,
                draft_answer=refusal,
                final_answer=refusal,
                reranked=[],
                include_retrieved_chunks=include_retrieved_chunks,
                hybrid=[],
            )

        draft, final = self.generate_answers(
            pipeline.question, settings, pipeline.reranked, tool_results=pipeline.tool_results
        )
        return self.build_query_response(
            status=QueryStatus.ANSWERED,
            conversation_id=conversation_id,
            tool_trace=pipeline.tool_trace,
            tool_results=pipeline.tool_results,
            draft_answer=draft,
            final_answer=final,
            reranked=pipeline.reranked,
            include_retrieved_chunks=include_retrieved_chunks,
            hybrid=pipeline.hybrid,
        )

    def answer_question(
        self,
        question: str,
        settings: GenerationSettings,
        *,
        tickers: list[str] | None = None,
        filing_date_from: str | None = None,
        filing_date_to: str | None = None,
        include_retrieved_chunks: bool = False,
        conversation_id: str | None = None,
        pre_tool_trace: list[ToolTraceEvent] | None = None,
    ) -> QueryResponse:
        """
        Execute tools-first planning, retrieval, and answer generation.

        TODO's
        ------
        - Add auto-refusal threshold based on retrieval/reranking scores and maybe planner confidence
        - Add date-intent inference tool ('latest filing' -> date filter)
        """

        pipeline = self.execute_query_pipeline(
            question=question,
            settings=settings,
            tickers=tickers,
            filing_date_from=filing_date_from,
            filing_date_to=filing_date_to,
            pre_tool_trace=pre_tool_trace,
        )
        return self.response_from_pipeline(
            pipeline=pipeline,
            settings=settings,
            conversation_id=conversation_id,
            include_retrieved_chunks=include_retrieved_chunks,
        )
