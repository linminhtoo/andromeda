from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, cast

from fastapi import Request
from pydantic import BaseModel, Field, ValidationError

from andromeda.dataclasses import ScoredChunk, TopChunk
from andromeda.retrieval.db import RetrievalFilters
from andromeda.finance_tools import FinanceToolResult, FinanceToolStatus, FinanceTools
from andromeda.llm.generation_controls import AnsweringEffort, GenerationSettings
from andromeda.ingestion.ingestion_jobs import normalize_ticker
from andromeda.llm.clients import ChatMessage, LLMClient
from andromeda.processing.metadata_models import chunk_metadata_from_value
from andromeda.llm.qa import (
    build_faithfulness_scrub_prompt,
    build_draft_prompt,
    build_multi_ticker_refine_prompt,
    build_multi_ticker_synthesis_prompt,
    build_refine_prompt,
    build_ticker_brief_prompt,
)
from andromeda.retrieval.retriever import CrossEncoderReranker, PostgresHybridRetriever
from andromeda.llm.streaming import TextDeltaBatcher, iter_chat_deltas, ndjson_bytes


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
    brief_max_tokens: int | None = None
    answering_effort: AnsweringEffort | None = None
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
    use_multi_ticker_briefs: bool | None = None
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
    use_multi_ticker_briefs: bool = False
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
    per_ticker_hybrid: dict[str, list[ScoredChunk]] = field(default_factory=dict)
    per_ticker_reranked: dict[str, list[ScoredChunk]] = field(default_factory=dict)
    per_ticker_briefs: dict[str, str] = field(default_factory=dict)
    plan_step_ms: float | None = None
    tools_step_ms: float | None = None
    retrieve_step_ms: float | None = None
    rerank_step_ms: float | None = None
    brief_step_ms: float | None = None


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
    def _question_has_explicit_period_scope(question: str) -> bool:
        lowered = f" {question.lower()} "
        if re.search(r"\b20\d{2}\b", lowered):
            return True
        tokens = (
            " quarter ",
            " q1 ",
            " q2 ",
            " q3 ",
            " q4 ",
            " fiscal year ",
            " fy ",
            " year ended ",
            " as of ",
            " during ",
            " in the latest filing ",
            " latest filing ",
        )
        return any(token in lowered for token in tokens)

    @staticmethod
    def _infer_filing_date_window_from_question(question: str) -> tuple[str, str] | None:
        """
        Infer an inclusive filing-date window from explicit years in the question.
        """

        years = sorted({int(token) for token in re.findall(r"\b(20\d{2})\b", question)})
        if not years:
            return None
        start_year = years[0]
        end_year = years[-1]
        if end_year - start_year > 6:
            return None
        return f"{start_year:04d}-01-01", f"{end_year:04d}-12-31"

    @staticmethod
    def _question_mentions_filing_narrative(question: str) -> bool:
        lowered = f" {question.lower()} "
        tokens = (
            " sec filing ",
            " sec filings ",
            " long-term investment ",
            " long term investment ",
            " investment thesis ",
            " bull-vs-bear ",
            " bull vs bear ",
            " business trajectory ",
            " growth driver ",
            " growth drivers ",
            " growth opportunities ",
            " key risks ",
            " material risks ",
            " downside risks ",
            " competitive positioning ",
            " competitive position ",
            " risk factor ",
            " management discussion ",
            " management commentary ",
            " md&a ",
            " discuss ",
            " explain ",
            " guidance ",
            " outlook ",
            " strategy ",
            " segment ",
            " capital allocation ",
            " margin resilience ",
            " cash-flow quality ",
            " cash flow quality ",
            " operational bottleneck ",
            " operational bottlenecks ",
            " dependencies ",
            " demand trends ",
            " customer behavior ",
            " trade-off ",
            " trade-offs ",
            " why ",
        )
        return any(token in lowered for token in tokens)

    @staticmethod
    def _question_mentions_growth_or_strategy(question: str) -> bool:
        lowered = " " + re.sub(r"[^a-z0-9]+", " ", question.lower()).strip() + " "
        tokens = (
            " growth ",
            " growth driver ",
            " growth drivers ",
            " growth opportunities ",
            " strategy ",
            " competitive positioning ",
            " positioning ",
            " business trajectory ",
            " long-term investment ",
            " long term investment ",
            " outlook ",
            " opportunities ",
            " investment thesis ",
            " capital allocation ",
        )
        return any(token in lowered for token in tokens)

    @staticmethod
    def _question_mentions_risk_dimension(question: str) -> bool:
        lowered = " " + re.sub(r"[^a-z0-9]+", " ", question.lower()).strip() + " "
        tokens = (" risk ", " risks ", " uncertainty ", " uncertainties ", " downside ", " bottleneck ")
        return any(token in lowered for token in tokens)

    @staticmethod
    def _question_mentions_capital_margin_or_cashflow(question: str) -> bool:
        lowered = " " + re.sub(r"[^a-z0-9]+", " ", question.lower()).strip() + " "
        tokens = (
            " capital allocation ",
            " capex ",
            " buyback ",
            " buybacks ",
            " debt ",
            " margin ",
            " margins ",
            " profitability ",
            " operating leverage ",
            " cash flow ",
            " cashflow ",
            " working capital ",
            " trade off ",
            " trade offs ",
            " trade-off ",
            " trade-offs ",
        )
        return any(token in lowered for token in tokens)

    @staticmethod
    def _question_mentions_execution_or_demand(question: str) -> bool:
        lowered = " " + re.sub(r"[^a-z0-9]+", " ", question.lower()).strip() + " "
        tokens = (
            " execution ",
            " operational ",
            " dependency ",
            " dependencies ",
            " bottleneck ",
            " bottlenecks ",
            " demand trend ",
            " demand trends ",
            " customer behavior ",
            " customer demand ",
            " supply chain ",
            " constraint ",
            " constraints ",
        )
        return any(token in lowered for token in tokens)

    def narrative_retrieval_queries(self, question: str) -> list[str]:
        """
        Build diversified retrieval queries for filing-narrative questions.
        """

        base = question.strip()
        if not base:
            return []
        queries = [base]
        if self._question_mentions_growth_or_strategy(question):
            queries.append(
                f"{base} Focus on explicitly stated growth drivers, strategy, revenue, segment performance, and demand."
            )
        if self._question_mentions_risk_dimension(question):
            queries.append(f"{base} Focus on explicitly stated risk factors, uncertainties, and constraints.")
        if self._question_mentions_capital_margin_or_cashflow(question):
            queries.append(
                f"{base} Focus on explicit capital allocation, profitability, margin, and cash-flow disclosures."
            )
        if self._question_mentions_execution_or_demand(question):
            queries.append(
                f"{base} Focus on explicit execution dependencies, demand commentary, and operational constraints."
            )

        deduped: list[str] = []
        seen: set[str] = set()
        for query in queries:
            key = query.lower().strip()
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(query)
        return deduped[:4]

    @staticmethod
    def _chunk_text_signature(sc: ScoredChunk) -> str:
        parsed = chunk_metadata_from_value(sc.chunk.metadata)
        section = parsed.section_path or ""
        headings = " ".join(sc.chunk.headings or [])
        text = (sc.chunk.text or "")[:300]
        return f"{section} {headings} {text}".lower()

    def _is_risk_chunk(self, sc: ScoredChunk) -> bool:
        text = self._chunk_text_signature(sc)
        tokens = ("risk factor", "risks", "uncertaint", "adverse", "regulatory", "cyber")
        return any(token in text for token in tokens)

    def _is_growth_or_strategy_chunk(self, sc: ScoredChunk) -> bool:
        text = self._chunk_text_signature(sc)
        if self._is_risk_chunk(sc):
            return False
        tokens = (
            "results of operations",
            "revenue",
            "segment",
            "overview",
            "management discussion",
            "md&a",
            "strategy",
            "competitive",
            "growth",
            "demand",
            "business",
        )
        return any(token in text for token in tokens)

    def _enforce_narrative_aspect_coverage(
        self, *, question: str, primary: list[ScoredChunk], fallback: list[ScoredChunk], limit: int
    ) -> list[ScoredChunk]:
        """
        Ensure narrative contexts include both growth/strategy and risk evidence when requested.
        """

        need_growth = self._question_mentions_growth_or_strategy(question)
        need_risk = self._question_mentions_risk_dimension(question)
        if not need_growth and not need_risk:
            return primary[:limit]

        selected: list[ScoredChunk] = []
        selected_ids: set[str] = set()

        def add_first_matching(pool: list[ScoredChunk], predicate) -> bool:
            for sc in pool:
                if not predicate(sc):
                    continue
                chunk_id = sc.chunk.id
                if chunk_id in selected_ids:
                    continue
                selected.append(sc)
                selected_ids.add(chunk_id)
                return True
            return False

        if need_growth:
            if not add_first_matching(primary, self._is_growth_or_strategy_chunk):
                add_first_matching(fallback, self._is_growth_or_strategy_chunk)
        if need_risk:
            if not add_first_matching(primary, self._is_risk_chunk):
                add_first_matching(fallback, self._is_risk_chunk)

        combined = self._dedupe_scored_chunks(primary + fallback)
        for sc in combined:
            if len(selected) >= limit:
                break
            if sc.chunk.id in selected_ids:
                continue
            selected.append(sc)
            selected_ids.add(sc.chunk.id)

        selected.sort(key=lambda item: item.score, reverse=True)
        return selected[:limit]

    @staticmethod
    def _mmr_token_set(sc: ScoredChunk) -> set[str]:
        parsed = chunk_metadata_from_value(sc.chunk.metadata)
        text = parsed.retrieval_text or sc.chunk.text or ""
        text = str(text).lower()
        tokens = re.findall(r"[a-z0-9]+", text)
        stopwords = {
            "the",
            "and",
            "for",
            "with",
            "that",
            "this",
            "from",
            "were",
            "are",
            "was",
            "have",
            "has",
            "had",
            "into",
            "than",
            "over",
            "under",
            "their",
            "they",
            "its",
            "our",
            "you",
            "your",
            "also",
            "may",
            "can",
            "could",
            "would",
            "should",
            "will",
        }
        return {token for token in tokens[:140] if len(token) > 2 and token not in stopwords}

    @staticmethod
    def _token_jaccard_similarity(left: set[str], right: set[str]) -> float:
        if not left or not right:
            return 0.0
        inter = len(left.intersection(right))
        union = len(left.union(right))
        if union <= 0:
            return 0.0
        return inter / union

    def apply_mmr_diversity(
        self, *, candidates: list[ScoredChunk], limit: int, lambda_mult: float = 0.78
    ) -> list[ScoredChunk]:
        """
        Select a relevance-diverse subset using a bounded MMR pass.
        """

        if limit <= 0:
            return []
        if len(candidates) <= 1:
            return candidates[:limit]

        pool_size = max(limit, min(len(candidates), limit * 3))
        pool = candidates[:pool_size]
        token_sets = [self._mmr_token_set(sc) for sc in pool]
        raw_scores = [float(sc.score) for sc in pool]
        score_min = min(raw_scores)
        score_max = max(raw_scores)

        def normalized_score(index: int) -> float:
            raw = raw_scores[index]
            if score_max <= score_min:
                return 1.0
            return (raw - score_min) / (score_max - score_min)

        selected_indices: list[int] = []
        remaining = set(range(len(pool)))
        while remaining and len(selected_indices) < limit:
            best_idx: int | None = None
            best_value = float("-inf")
            for idx in remaining:
                relevance = normalized_score(idx)
                if not selected_indices:
                    novelty_penalty = 0.0
                else:
                    novelty_penalty = max(
                        self._token_jaccard_similarity(token_sets[idx], token_sets[sel]) for sel in selected_indices
                    )
                mmr_value = (lambda_mult * relevance) - ((1.0 - lambda_mult) * novelty_penalty)
                if mmr_value > best_value:
                    best_value = mmr_value
                    best_idx = idx
            if best_idx is None:
                break
            remaining.remove(best_idx)
            selected_indices.append(best_idx)

        out = [pool[idx] for idx in selected_indices]
        out.sort(key=lambda item: item.score, reverse=True)
        return out[:limit]

    @staticmethod
    def mmr_diversity_enabled() -> bool:
        """
        Return whether experimental MMR chunk diversity is enabled.
        """

        raw = (os.getenv("FINRAG_ENABLE_MMR_DIVERSITY") or "0").strip().lower()
        return raw in {"1", "true", "yes", "on"}

    def _question_is_simple_numeric_metric(self, question: str) -> bool:
        """
        Return whether the question is a direct numeric metric lookup.
        """

        mentions_metrics = self._question_mentions_financial_metrics(question) or self._question_mentions_market_data(
            question
        )
        mentions_narrative = self._question_mentions_filing_narrative(question)
        mentions_comparison = self._question_mentions_comparison(question)
        has_period_scope = self._question_has_explicit_period_scope(question)
        lowered = f" {question.lower()} "
        has_explicit_numeric_intent = any(
            token in lowered
            for token in (
                " what was ",
                " what is ",
                " how much ",
                " amount ",
                " total ",
                " value ",
                " figure ",
                " give me ",
            )
        )
        token_count = len(question.split())
        return (
            mentions_metrics
            and not mentions_narrative
            and not mentions_comparison
            and not has_period_scope
            and has_explicit_numeric_intent
            and token_count <= 24
        )

    def resolve_tool_usage_from_decision(self, *, question: str, decision: PlannerDecision) -> tuple[bool, bool, bool]:
        """
        Resolve planner tool flags into effective `use_rag`, `use_yfinance`, and `use_edgar_financials`.
        """

        simple_numeric_query = self._question_is_simple_numeric_metric(question)
        narrative_query = self._question_mentions_filing_narrative(question)
        period_scoped_metric_query = self._question_mentions_financial_metrics(
            question
        ) and self._question_has_explicit_period_scope(question)
        market_data_query = self._question_mentions_market_data(question)
        financial_metric_query = self._question_mentions_financial_metrics(question)

        use_yfinance = bool(decision.use_yfinance) if decision.use_yfinance is not None else market_data_query
        use_edgar_financials = (
            bool(decision.use_edgar_financials) if decision.use_edgar_financials is not None else financial_metric_query
        )

        if simple_numeric_query:
            # For direct numeric lookup queries, choose the most relevant finance tool first.
            if market_data_query and not financial_metric_query:
                use_yfinance = True
                use_edgar_financials = False
            elif financial_metric_query and not market_data_query:
                use_yfinance = False
                use_edgar_financials = True
            else:
                use_yfinance = market_data_query
                use_edgar_financials = financial_metric_query or not market_data_query
        elif narrative_query:
            # For filing-narrative requests, avoid mixing in external market/tool facts.
            use_edgar_financials = False
            use_yfinance = False

        if decision.use_rag is not None:
            use_rag = bool(decision.use_rag)
        else:
            if simple_numeric_query:
                use_rag = False
            elif narrative_query:
                use_rag = True
            elif use_yfinance or use_edgar_financials:
                use_rag = False
            else:
                use_rag = True

        if simple_numeric_query:
            use_rag = False
        elif narrative_query:
            use_rag = True
        elif period_scoped_metric_query:
            # Period-specific metric questions usually need filing chunks for exact timeframe grounding.
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
                    "use_per_ticker_retrieval=true and use_multi_ticker_briefs=true.\n"
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
                    "use_per_ticker_retrieval, use_multi_ticker_briefs, use_rag, use_yfinance, use_edgar_financials."
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
                use_multi_ticker_briefs=(
                    True
                    if len(explicit_tickers if explicit_tickers else inferred) > 1
                    and self._question_mentions_comparison(question)
                    else None
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
                        "use_multi_ticker_briefs": decision.use_multi_ticker_briefs,
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
        if resolved_filing_date_from is None and resolved_filing_date_to is None:
            inferred_window = self._infer_filing_date_window_from_question(question)
            if inferred_window is not None:
                resolved_filing_date_from, resolved_filing_date_to = inferred_window
                trace.append(
                    self._tool_event(
                        "infer_question_date_window",
                        args={"filing_date_from": resolved_filing_date_from, "filing_date_to": resolved_filing_date_to},
                        result="Applied year window inferred from question text.",
                    )
                )
        filters = self.build_retrieval_filters(
            tickers=planned_tickers, filing_date_from=resolved_filing_date_from, filing_date_to=resolved_filing_date_to
        )
        use_per_ticker = (
            bool(decision.use_per_ticker_retrieval)
            if decision.use_per_ticker_retrieval is not None
            else (len(planned_tickers) > 1 or self._question_mentions_comparison(question))
        )
        use_multi_ticker_briefs = (
            bool(decision.use_multi_ticker_briefs)
            if decision.use_multi_ticker_briefs is not None
            else (use_per_ticker and len(planned_tickers) > 1 and self._question_mentions_comparison(question))
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
                    "use_multi_ticker_briefs": use_multi_ticker_briefs,
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
            use_multi_ticker_briefs=use_multi_ticker_briefs,
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

        disable_finance_tools = (os.getenv("FINRAG_DISABLE_FINANCE_TOOLS") or "").strip().lower()
        if disable_finance_tools in {"1", "true", "yes", "on"}:
            return [], [
                self._tool_event("finance_tools_skip", result="Finance tool execution disabled by environment.")
            ]

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

    @staticmethod
    def has_actionable_tool_results(results: list[FinanceToolResult]) -> bool:
        """
        Return whether tool execution produced at least one usable result.
        """

        for item in results:
            if item.status == FinanceToolStatus.OK:
                return True
        return False

    def retrieve_chunks(
        self, question: str, settings: GenerationSettings, *, filters: RetrievalFilters
    ) -> list[ScoredChunk]:
        """
        Retrieve hybrid candidates for a question.
        """

        return self.retrieve_chunks_with_limit(question=question, top_k=settings.top_k_retrieve, filters=filters)

    def retrieve_chunks_with_limit(self, *, question: str, top_k: int, filters: RetrievalFilters) -> list[ScoredChunk]:
        """
        Retrieve hybrid candidates with an explicit retrieval limit.
        """

        return self.retriever.retrieve_hybrid(
            question, top_k_semantic=top_k, top_k_bm25=top_k, top_k_final=top_k, filters=filters
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
            retrieval_queries = [question]
            if planned.use_rag and self._question_mentions_filing_narrative(question):
                retrieval_queries = self.narrative_retrieval_queries(question)

            if len(retrieval_queries) == 1:
                hybrid = self.retrieve_chunks(question, settings, filters=planned.filters)
            else:
                per_query_top_k = max(8, settings.top_k_retrieve // len(retrieval_queries))
                merged: list[ScoredChunk] = []
                for retrieval_query in retrieval_queries:
                    merged.extend(
                        self.retrieve_chunks_with_limit(
                            question=retrieval_query, top_k=per_query_top_k, filters=planned.filters
                        )
                    )
                hybrid = self._dedupe_scored_chunks(merged)
            trace = [
                self._tool_event(
                    "retrieve_chunks",
                    args={
                        "tickers": list(planned.filters.normalized_tickers()),
                        "top_k_retrieve": settings.top_k_retrieve,
                        "retrieval_queries": retrieval_queries,
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

    def _retrieve_and_rerank_for_ticker(
        self, *, question: str, settings: GenerationSettings, planned: PlannedQuery, ticker: str
    ) -> tuple[list[ScoredChunk], list[ScoredChunk]]:
        filing_date_from = (
            planned.filters.filing_date_from.isoformat()
            if planned.filters and planned.filters.filing_date_from
            else None
        )
        filing_date_to = (
            planned.filters.filing_date_to.isoformat() if planned.filters and planned.filters.filing_date_to else None
        )
        ticker_filters = self.build_retrieval_filters(
            tickers=[ticker], filing_date_from=filing_date_from, filing_date_to=filing_date_to
        )
        ticker_hybrid = self.retrieve_chunks(question, settings, filters=ticker_filters)
        ticker_reranked = self.rerank_chunks(question, settings, ticker_hybrid)
        return ticker_hybrid, ticker_reranked

    def build_ticker_brief_prompt(
        self,
        *,
        question: str,
        ticker: str,
        settings: GenerationSettings,
        reranked: list[ScoredChunk],
        tool_results: list[FinanceToolResult] | None = None,
    ) -> list[ChatMessage]:
        """
        Build prompt for one ticker brief inside multi-ticker pipeline.
        """

        return build_ticker_brief_prompt(
            question=question,
            ticker=ticker,
            reranked=reranked,
            brief_max_tokens=settings.brief_max_tokens,
            answer_style=settings.answer_style,
            system_extra=self.compose_prompt_extra(question=question, reranked=reranked),
            tool_context=self.finance_tools.tool_context_text(tool_results or []),
        )

    @staticmethod
    def _effort_temperature(effort: AnsweringEffort) -> float:
        if effort == AnsweringEffort.LOW:
            return 0.0
        if effort == AnsweringEffort.HIGH:
            return 0.2
        return 0.1

    def generate_ticker_briefs(
        self,
        *,
        question: str,
        settings: GenerationSettings,
        per_ticker_reranked: dict[str, list[ScoredChunk]],
        tool_results: list[FinanceToolResult] | None = None,
    ) -> dict[str, str]:
        """
        Generate per-ticker briefs in parallel for multi-ticker synthesis.
        """

        tickers = list(per_ticker_reranked.keys())
        if not tickers:
            return {}

        out: dict[str, str] = {}

        def run_for_ticker(ticker: str) -> tuple[str, str]:
            prompt = self.build_ticker_brief_prompt(
                question=question,
                ticker=ticker,
                settings=settings,
                reranked=per_ticker_reranked[ticker],
                tool_results=tool_results,
            )
            brief = self.llm.chat(
                prompt,
                temperature=self._effort_temperature(settings.answering_effort),
                max_tokens=settings.brief_max_tokens,
            )
            return ticker, brief

        worker_count = max(1, min(len(tickers), 8))
        with ThreadPoolExecutor(max_workers=worker_count) as ex:
            futures = [ex.submit(run_for_ticker, ticker) for ticker in tickers]
            for future in futures:
                ticker, brief = future.result()
                out[ticker] = brief
        return out

    def multi_ticker_synthesis_prompt(
        self,
        *,
        question: str,
        settings: GenerationSettings,
        per_ticker_briefs: dict[str, str],
        tool_results: list[FinanceToolResult] | None = None,
        draft_answer: str | None = None,
    ) -> list[ChatMessage]:
        """
        Build final synthesis prompt from per-ticker briefs.
        """

        tool_context = self.finance_tools.tool_context_text(tool_results or [])
        if settings.enable_refine and draft_answer is not None:
            return build_multi_ticker_refine_prompt(
                question=question,
                draft=draft_answer,
                per_ticker_briefs=per_ticker_briefs,
                final_max_tokens=settings.final_max_tokens,
                answer_style=settings.answer_style,
                answering_effort=settings.answering_effort,
                tool_context=tool_context,
            )
        return build_multi_ticker_synthesis_prompt(
            question=question,
            per_ticker_briefs=per_ticker_briefs,
            final_max_tokens=settings.final_max_tokens,
            answer_style=settings.answer_style,
            answering_effort=settings.answering_effort,
            tool_context=tool_context,
        )

    def should_apply_faithfulness_scrub(self, question: str) -> bool:
        """
        Return whether strict factual scrub should run for the final answer.
        """

        return self._question_mentions_filing_narrative(question)

    def scrub_answer_for_faithfulness(
        self,
        *,
        question: str,
        settings: GenerationSettings,
        candidate_answer: str,
        reranked: list[ScoredChunk],
        tool_results: list[FinanceToolResult] | None = None,
    ) -> str:
        """
        Run one strict editing pass to remove unsupported claims.
        """

        if not candidate_answer.strip():
            return candidate_answer
        if not reranked:
            return candidate_answer
        prompt = build_faithfulness_scrub_prompt(
            question=question,
            candidate_answer=candidate_answer,
            reranked=reranked,
            final_max_tokens=settings.final_max_tokens,
            answer_style=settings.answer_style,
            tool_context=self.finance_tools.tool_context_text(tool_results or []),
        )
        return self.llm.chat(prompt, temperature=0.0, max_tokens=settings.final_max_tokens)

    def generate_answers_from_ticker_briefs(
        self,
        *,
        question: str,
        settings: GenerationSettings,
        per_ticker_briefs: dict[str, str],
        reranked_context: list[ScoredChunk] | None = None,
        tool_results: list[FinanceToolResult] | None = None,
    ) -> tuple[str, str]:
        """
        Generate final answer by synthesizing per-ticker briefs.
        """

        draft = self.llm.chat(
            self.multi_ticker_synthesis_prompt(
                question=question, settings=settings, per_ticker_briefs=per_ticker_briefs, tool_results=tool_results
            ),
            temperature=self._effort_temperature(settings.answering_effort),
            max_tokens=settings.final_max_tokens,
        )
        final = draft
        if settings.enable_refine:
            final = self.llm.chat(
                self.multi_ticker_synthesis_prompt(
                    question=question,
                    settings=settings,
                    per_ticker_briefs=per_ticker_briefs,
                    tool_results=tool_results,
                    draft_answer=draft,
                ),
                temperature=0.0,
                max_tokens=settings.final_max_tokens,
            )
        if settings.enable_refine and self.should_apply_faithfulness_scrub(question) and reranked_context:
            final = self.scrub_answer_for_faithfulness(
                question=question,
                settings=settings,
                candidate_answer=final,
                reranked=reranked_context,
                tool_results=tool_results,
            )
        return draft, final

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
            # FIXME: current logic is too naive.
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
        if planned.use_rag and self._question_mentions_filing_narrative(question):
            if self.mmr_diversity_enabled() and (
                self._question_mentions_growth_or_strategy(question) or self._question_mentions_risk_dimension(question)
            ):
                reranked = self.apply_mmr_diversity(candidates=reranked, limit=settings.top_k_rerank)
                trace.append(
                    self._tool_event(
                        "apply_mmr_diversity",
                        args={"top_k_rerank": settings.top_k_rerank, "lambda_mult": 0.78},
                        result=f"Applied bounded MMR diversification (size={len(reranked)}).",
                    )
                )
            reranked = self._enforce_narrative_aspect_coverage(
                question=question, primary=reranked, fallback=hybrid, limit=settings.top_k_rerank
            )
            trace.append(
                self._tool_event(
                    "enforce_narrative_aspect_coverage",
                    args={"top_k_rerank": settings.top_k_rerank},
                    result=(f"Adjusted reranked list for narrative aspect coverage (size={len(reranked)})."),
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
        generate_multi_ticker_briefs: bool = True,
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

        use_rag_for_execution = planned.use_rag
        if not use_rag_for_execution:
            if self.has_actionable_tool_results(execution.tool_results):
                execution.tool_trace.append(
                    self._tool_event(
                        "rag_function_skip",
                        args={"reason": "planner_use_rag_false"},
                        result="Skipped RAG retrieval function per planner tool decision.",
                    )
                )
                return execution
            execution.tool_trace.append(
                self._tool_event(
                    "rag_function_fallback",
                    args={"reason": "no_actionable_tool_results"},
                    result="Planner disabled RAG, but finance tools returned no usable data; falling back to retrieval.",
                )
            )
            use_rag_for_execution = True

        if planned.use_multi_ticker_briefs and len(planned.tickers) > 1:
            retrieve_t0 = time.perf_counter()
            per_ticker_hybrid: dict[str, list[ScoredChunk]] = {}
            per_ticker_reranked: dict[str, list[ScoredChunk]] = {}
            worker_count = max(1, min(len(planned.tickers), 8))
            with ThreadPoolExecutor(max_workers=worker_count) as ex:
                futures = {
                    ticker: ex.submit(
                        self._retrieve_and_rerank_for_ticker,
                        question=question,
                        settings=settings,
                        planned=planned,
                        ticker=ticker,
                    )
                    for ticker in planned.tickers
                }
                for ticker, future in futures.items():
                    ticker_hybrid, ticker_reranked = future.result()
                    per_ticker_hybrid[ticker] = ticker_hybrid
                    per_ticker_reranked[ticker] = ticker_reranked
                    execution.tool_trace.append(
                        self._tool_event(
                            "retrieve_rerank_per_ticker",
                            args={
                                "ticker": ticker,
                                "top_k_retrieve": settings.top_k_retrieve,
                                "top_k_rerank": settings.top_k_rerank,
                                "enable_rerank": settings.enable_rerank,
                            },
                            result=(
                                f"Retrieved {len(ticker_hybrid)} and reranked {len(ticker_reranked)} chunks for "
                                f"{ticker}."
                            ),
                        )
                    )
            execution.retrieve_step_ms = (time.perf_counter() - retrieve_t0) * 1000.0
            execution.rerank_step_ms = execution.retrieve_step_ms
            execution.per_ticker_hybrid = per_ticker_hybrid
            execution.per_ticker_reranked = per_ticker_reranked
            execution.hybrid = self._dedupe_scored_chunks(
                [item for chunks in per_ticker_hybrid.values() for item in chunks]
            )
            execution.reranked = self._dedupe_scored_chunks(
                [item for chunks in per_ticker_reranked.values() for item in chunks]
            )[: settings.top_k_rerank]
            execution.tool_trace.append(
                self._tool_event(
                    "merge_multi_ticker_candidates",
                    args={"tickers": list(per_ticker_reranked.keys())},
                    result=(
                        "Merged per-ticker candidates into "
                        f"{len(execution.hybrid)} retrieved and {len(execution.reranked)} reranked chunks."
                    ),
                )
            )

            if generate_multi_ticker_briefs:
                brief_t0 = time.perf_counter()
                execution.per_ticker_briefs = self.generate_ticker_briefs(
                    question=question,
                    settings=settings,
                    per_ticker_reranked=per_ticker_reranked,
                    tool_results=execution.tool_results,
                )
                execution.brief_step_ms = (time.perf_counter() - brief_t0) * 1000.0
                execution.tool_trace.append(
                    self._tool_event(
                        "generate_per_ticker_briefs",
                        args={
                            "tickers": list(execution.per_ticker_briefs.keys()),
                            "brief_max_tokens": settings.brief_max_tokens,
                            "answering_effort": settings.answering_effort.value,
                        },
                        result=f"Generated {len(execution.per_ticker_briefs)} per-ticker briefs in parallel.",
                    )
                )
            else:
                execution.tool_trace.append(
                    self._tool_event(
                        "generate_per_ticker_briefs_skip",
                        result="Skipped per-ticker brief generation during pipeline execution.",
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
            system_extra=self.compose_prompt_extra(question=question, reranked=reranked),
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
            system_extra=self.compose_prompt_extra(question=question, reranked=reranked),
            tool_context=tool_context,
        )

    def prompt_extra_for_question(self, question: str) -> str | None:
        """
        Build targeted system prompt guidance for the current question.
        """

        if self._question_mentions_filing_narrative(question):
            years = self._requested_years(question)
            year_scope_note = ""
            if years:
                year_scope_note = (
                    "- Year-scope handling: when year(s) are requested, explicitly separate filing year from covered "
                    "period before any analysis.\n"
                    "- Never convert filing-year references into full-year performance claims unless cited evidence "
                    "explicitly reports that year as the covered period.\n"
                    "- If year scope is ambiguous, make the ambiguity explicit and avoid unsupported assumptions.\n"
                )
            return (
                "Narrative evidence mode:\n"
                "- Output at most 6 material points.\n"
                "- For each point, include: point, why it matters, and one short direct quote with citation.\n"
                "- Do not include a point unless a direct quote supports it.\n"
                "- Keep quotes short and verbatim from context/tool context.\n"
                "- Never cite doc/chunk IDs that are absent from the provided context headers.\n"
                "- If a requested point has no explicit quote support, state: "
                "'Not explicitly stated in the provided context.'\n" + year_scope_note
            )
        return None

    @staticmethod
    def _requested_years(question: str) -> list[int]:
        """
        Extract distinct requested years from question text.
        """

        years = {int(token) for token in re.findall(r"\b20\d{2}\b", question)}
        return sorted(years)

    @staticmethod
    def _year_from_iso_date(value: str | None) -> int | None:
        """
        Parse a year from an ISO date string.
        """

        if not isinstance(value, str):
            return None
        match = re.match(r"^(20\d{2})-\d{2}-\d{2}$", value.strip())
        if match is None:
            return None
        return int(match.group(1))

    def period_scope_prompt_extra(self, *, question: str, reranked: list[ScoredChunk]) -> str | None:
        """
        Add dynamic year-scope reminders based on filing-year vs covered-period metadata.
        """

        requested_years = self._requested_years(question)
        if not requested_years or not reranked:
            return None

        top_window = reranked[: min(len(reranked), 20)]
        filing_year_counts: dict[int, int] = {}
        period_year_counts: dict[int, int] = {}
        for sc in top_window:
            parsed = chunk_metadata_from_value(sc.chunk.metadata)
            doc = parsed.doc
            filing_year = self._year_from_iso_date(doc.filing_date if doc is not None else None)
            period_year = self._year_from_iso_date(doc.period_end_date if doc is not None else None)
            if filing_year is not None:
                filing_year_counts[filing_year] = filing_year_counts.get(filing_year, 0) + 1
            if period_year is not None:
                period_year_counts[period_year] = period_year_counts.get(period_year, 0) + 1

        if not filing_year_counts and not period_year_counts:
            return None

        lines: list[str] = []
        for year in requested_years:
            filing_hits = filing_year_counts.get(year, 0)
            period_hits = period_year_counts.get(year, 0)
            if filing_hits > 0 and period_hits == 0:
                lines.append(
                    f"Requested year {year} appears as filing-year metadata but not covered-period metadata in top "
                    "context; do not claim operating results for that year unless explicitly stated."
                )
            elif filing_hits > 0 and period_hits < filing_hits:
                lines.append(
                    f"Requested year {year} has partial covered-period support relative to filing-year matches; "
                    "qualify conclusions with exact period scope."
                )

        if not lines:
            return None

        filing_years = ", ".join(str(year) for year in sorted(filing_year_counts))
        period_years = ", ".join(str(year) for year in sorted(period_year_counts)) if period_year_counts else "(none)"
        return (
            "Period scope notes:\n"
            f"- Observed filing years in top context: {filing_years}\n"
            f"- Observed covered-period years in top context: {period_years}\n"
            "- " + "\n- ".join(lines)
        )

    def context_coverage_prompt_extra(self, *, question: str, reranked: list[ScoredChunk]) -> str | None:
        """
        Add missing-evidence guardrails when requested narrative dimensions are absent in context.
        """

        if not reranked:
            return None
        if not self._question_mentions_filing_narrative(question):
            return None

        top_window = reranked[: min(len(reranked), 14)]
        growth_count = sum(1 for sc in top_window if self._is_growth_or_strategy_chunk(sc))
        risk_count = sum(1 for sc in top_window if self._is_risk_chunk(sc))

        lines: list[str] = []
        if self._question_mentions_growth_or_strategy(question) and growth_count == 0:
            lines.append(
                "Retrieved context does not contain explicit growth/strategy evidence; state that these points are "
                "not explicitly stated unless directly quoted."
            )
        if self._question_mentions_risk_dimension(question) and risk_count == 0:
            lines.append(
                "Retrieved context does not contain explicit risk disclosures; state that risk details are not "
                "explicitly stated unless directly quoted."
            )
        period_scope_extra = self.period_scope_prompt_extra(question=question, reranked=reranked)
        if period_scope_extra:
            lines.append(period_scope_extra)
        if not lines:
            return None
        return "Context coverage notes:\n- " + "\n- ".join(lines)

    def compose_prompt_extra(self, *, question: str, reranked: list[ScoredChunk]) -> str | None:
        """
        Merge static question guidance and dynamic context-coverage guidance.
        """

        parts: list[str] = []
        static_extra = self.prompt_extra_for_question(question)
        if static_extra:
            parts.append(static_extra)
        coverage_extra = self.context_coverage_prompt_extra(question=question, reranked=reranked)
        if coverage_extra:
            parts.append(coverage_extra)
        if not parts:
            return None
        return "\n\n".join(parts)

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
        final = draft
        if settings.enable_refine:
            final = self.llm.chat(
                self.final_prompt(question, settings, reranked, draft_answer=draft, tool_results=tool_results),
                temperature=0.0,
            )
        if settings.enable_refine and self.should_apply_faithfulness_scrub(question):
            final = self.scrub_answer_for_faithfulness(
                question=question,
                settings=settings,
                candidate_answer=final,
                reranked=reranked,
                tool_results=tool_results,
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

        if pipeline.planned.use_multi_ticker_briefs and pipeline.per_ticker_briefs:
            draft, final = self.generate_answers_from_ticker_briefs(
                question=pipeline.question,
                settings=settings,
                per_ticker_briefs=pipeline.per_ticker_briefs,
                reranked_context=pipeline.reranked,
                tool_results=pipeline.tool_results,
            )
        else:
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
