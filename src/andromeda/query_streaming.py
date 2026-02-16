import asyncio
import os
import threading
import time
import uuid
from dataclasses import dataclass
from collections.abc import AsyncIterator, Callable

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from loguru import logger

from andromeda.generation_controls import GenerationSettings
from andromeda.metadata_models import chunk_metadata_from_value
from andromeda.query_runtime import (
    QueryStatus,
    QueryPipelineExecution,
    QueryRequest,
    QueryResponse,
    QueryStreamRequest,
    RAGService,
    StreamStageResult,
    ToolTraceEvent,
    stream_text_stage,
)
from andromeda.streaming import ndjson_bytes, stream_chunks_max, stream_chunks_preview_chars, stream_draft_enabled


class StreamCancelRegistry:
    """
    Manage cancellation events keyed by streaming request id.
    """

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.events: dict[str, threading.Event] = {}

    def register(self, *, request_id: str | None) -> tuple[str, threading.Event]:
        resolved_id = (request_id or "").strip() or str(uuid.uuid4())
        with self.lock:
            evt = self.events.get(resolved_id)
            if evt is None:
                evt = threading.Event()
                self.events[resolved_id] = evt
            return resolved_id, evt

    def cancel(self, *, request_id: str) -> bool:
        with self.lock:
            evt = self.events.get(request_id)
        if evt is None:
            return False
        evt.set()
        return True

    def cleanup(self, *, request_id: str) -> None:
        with self.lock:
            self.events.pop(request_id, None)


@dataclass
class StreamAnswerAccumulator:
    draft: str = ""
    final: str = ""
    final_step_ms: float | None = None


async def stream_per_ticker_briefs(
    *,
    request: Request,
    cancel_evt: threading.Event,
    rag_service: RAGService,
    pipeline: QueryPipelineExecution,
    settings: GenerationSettings,
    started_ms: int,
    timing_ms: dict[str, float],
) -> AsyncIterator[bytes]:
    """
    Stream per-ticker brief deltas from parallel subagents and persist final briefs on pipeline.
    """

    tickers = list(pipeline.per_ticker_reranked.keys())
    if not tickers:
        return

    yield ndjson_bytes({"type": "status", "step": "briefs", "message": "Generating per-ticker briefs…"})
    yield ndjson_bytes({"type": "briefs_start", "tickers": tickers, "elapsed_ms": _elapsed(started_ms)})

    t0 = time.perf_counter()
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
    worker_threads: list[threading.Thread] = []
    effort_temperature = rag_service._effort_temperature(settings.answering_effort)

    def run_worker(ticker: str) -> None:
        text = ""
        try:
            prompt = rag_service.build_ticker_brief_prompt(
                question=pipeline.question,
                ticker=ticker,
                settings=settings,
                reranked=pipeline.per_ticker_reranked[ticker],
                tool_results=pipeline.tool_results,
            )
            for delta in rag_service.llm.chat_stream(prompt, temperature=effort_temperature):
                if cancel_evt.is_set():
                    break
                text += delta
                payload: dict[str, object] = {"kind": "delta", "ticker": ticker, "delta": delta}
                loop.call_soon_threadsafe(queue.put_nowait, payload)
        finally:
            payload_done: dict[str, object] = {"kind": "done", "ticker": ticker, "text": text}
            loop.call_soon_threadsafe(queue.put_nowait, payload_done)

    for ticker in tickers:
        thread = threading.Thread(target=run_worker, args=(ticker,), daemon=True)
        thread.start()
        worker_threads.append(thread)

    remaining = len(tickers)
    briefs: dict[str, str] = {}
    while remaining > 0:
        if await request.is_disconnected():
            cancel_evt.set()
        if cancel_evt.is_set():
            break
        item = await queue.get()
        kind = str(item.get("kind") or "")
        ticker = str(item.get("ticker") or "")
        if kind == "delta":
            yield ndjson_bytes(
                {
                    "type": "ticker_brief_delta",
                    "ticker": ticker,
                    "delta": str(item.get("delta") or ""),
                    "elapsed_ms": _elapsed(started_ms),
                }
            )
            continue
        if kind == "done":
            text = str(item.get("text") or "")
            briefs[ticker] = text
            remaining -= 1
            yield ndjson_bytes(
                {"type": "ticker_brief_done", "ticker": ticker, "chars": len(text), "elapsed_ms": _elapsed(started_ms)}
            )

    for thread in worker_threads:
        await asyncio.to_thread(thread.join, 0.2)

    pipeline.per_ticker_briefs = briefs
    brief_ms = (time.perf_counter() - t0) * 1000.0
    pipeline.brief_step_ms = brief_ms
    timing_ms["brief_ms"] = brief_ms
    yield ndjson_bytes(
        {"type": "briefs_done", "count": len(briefs), "step_ms": _step_ms(brief_ms), "elapsed_ms": _elapsed(started_ms)}
    )


def stream_chunk_payload(*, scored_chunk, preview_chars: int, text_chars: int) -> dict:
    """
    Convert scored chunk to stream-safe payload.
    """

    parsed = chunk_metadata_from_value(scored_chunk.chunk.metadata)
    base_text = parsed.retrieval_text or scored_chunk.chunk.text or ""
    text = str(base_text).strip()
    preview = text[:preview_chars] if preview_chars > 0 else ""
    chunk_text = text[:text_chars] if text_chars > 0 else ""
    source_text = str(scored_chunk.chunk.text or "")
    return {
        "chunk_id": scored_chunk.chunk.id,
        "doc_id": scored_chunk.chunk.doc_id,
        "page_no": scored_chunk.chunk.page_no,
        "headings": scored_chunk.chunk.headings,
        "score": scored_chunk.score,
        "preview": preview,
        "source": scored_chunk.chunk.source,
        "text": chunk_text,
        "source_text": source_text,
        "metadata": RAGService._chunk_metadata_for_ui(scored_chunk.chunk.metadata),
    }


async def run_query_stream(
    *,
    req: QueryStreamRequest,
    request: Request,
    rag_service: RAGService,
    request_id: str,
    cancel_evt: threading.Event,
    resolve_conversation_question: Callable[[str | None, str], tuple[str, str, list[ToolTraceEvent]]],
    update_conversation_after_query: Callable[[str | None, str, QueryResponse], None],
    append_history: Callable[[QueryRequest, QueryResponse, dict[str, float] | None], None],
    resolve_generation: Callable[[QueryRequest], GenerationSettings],
    request_with_resolved_settings: Callable[[QueryRequest, GenerationSettings], QueryRequest],
) -> AsyncIterator[bytes]:
    """
    Execute streaming query flow and yield NDJSON events.

    TODO's
    ------
    - store question/answer pairs into postgresDB for analysis
    """

    effective_question, conversation_id, pre_tool_trace = resolve_conversation_question(
        req.conversation_id, req.question
    )
    base_req = QueryRequest(**(req.model_dump(exclude={"request_id"}) | {"conversation_id": conversation_id}))
    settings = resolve_generation(base_req)
    req_resolved = request_with_resolved_settings(base_req, settings)
    started_ms = int(time.time() * 1000)

    preview_chars = max(0, stream_chunks_preview_chars())
    max_chunks = max(0, stream_chunks_max())
    try:
        text_chars = int((os.getenv("FINRAG_STREAM_CHUNKS_TEXT_CHARS", "1000") or "1000").strip())
    except ValueError:
        text_chars = 1000
    text_chars = max(0, text_chars)

    timing_ms: dict[str, float] = {}

    try:
        yield ndjson_bytes({"type": "start", "request_id": request_id, "conversation_id": conversation_id})

        yield ndjson_bytes({"type": "status", "step": "plan", "message": "Planning query tools…"})
        yield ndjson_bytes({"type": "status", "step": "tools", "message": "Fetching finance tools…"})
        yield ndjson_bytes({"type": "status", "step": "retrieve", "message": "Retrieving chunks…"})
        yield ndjson_bytes(
            {
                "type": "status",
                "step": "rerank",
                "message": ("Reranking chunks…" if settings.enable_rerank else "Skipping rerank (mode preset)…"),
            }
        )

        pipeline = await asyncio.to_thread(
            rag_service.execute_query_pipeline,
            question=effective_question,
            settings=settings,
            tickers=req.tickers,
            filing_date_from=req.filing_date_from,
            filing_date_to=req.filing_date_to,
            pre_tool_trace=pre_tool_trace,
            generate_multi_ticker_briefs=False,
        )

        _record_timing(timing_ms=timing_ms, pipeline=pipeline)

        if pipeline.planned.status != QueryStatus.ANSWERED:
            response = rag_service.response_from_pipeline(
                pipeline=pipeline, settings=settings, conversation_id=conversation_id, include_retrieved_chunks=False
            )
            update_conversation_after_query(conversation_id, effective_question, response)
            total_ms = (time.time() * 1000) - started_ms
            timing_ms["total_ms"] = float(total_ms)
            append_history(req_resolved, response, timing_ms)
            yield ndjson_bytes(
                {
                    "type": "done",
                    "request_id": request_id,
                    "elapsed_ms": int(total_ms),
                    "timing_ms": {k: (float(v) if v is not None else None) for k, v in timing_ms.items()},
                    "response": jsonable_encoder(response),
                }
            )
            return

        if await request.is_disconnected():
            cancel_evt.set()
        if cancel_evt.is_set():
            yield ndjson_bytes({"type": "cancelled", "request_id": request_id, "elapsed_ms": _elapsed(started_ms)})
            return

        yield ndjson_bytes(
            {
                "type": "tool_results",
                "count": len(pipeline.tool_results),
                "results": jsonable_encoder(rag_service.serialize_finance_tool_results(pipeline.tool_results)),
                "step_ms": _step_ms(pipeline.tools_step_ms),
                "elapsed_ms": _elapsed(started_ms),
            }
        )

        retrieved_payload = [
            stream_chunk_payload(scored_chunk=sc, preview_chars=preview_chars, text_chars=text_chars)
            for sc in pipeline.hybrid
        ]
        if max_chunks:
            retrieved_payload = retrieved_payload[:max_chunks]
        yield ndjson_bytes(
            {
                "type": "retrieved",
                "count": len(pipeline.hybrid),
                "chunks": retrieved_payload,
                "step_ms": _step_ms(pipeline.retrieve_step_ms),
                "elapsed_ms": _elapsed(started_ms),
            }
        )

        reranked_payload = [
            stream_chunk_payload(scored_chunk=sc, preview_chars=preview_chars, text_chars=text_chars)
            for sc in pipeline.reranked
        ]
        yield ndjson_bytes(
            {
                "type": "reranked",
                "count": len(pipeline.reranked),
                "chunks": reranked_payload,
                "step_ms": _step_ms(pipeline.rerank_step_ms),
                "elapsed_ms": _elapsed(started_ms),
            }
        )

        if pipeline.planned.use_multi_ticker_briefs and pipeline.per_ticker_reranked:
            async for payload in stream_per_ticker_briefs(
                request=request,
                cancel_evt=cancel_evt,
                rag_service=rag_service,
                pipeline=pipeline,
                settings=settings,
                started_ms=started_ms,
                timing_ms=timing_ms,
            ):
                yield payload

        answer = StreamAnswerAccumulator()
        async for payload in stream_answer_text(
            request=request,
            cancel_evt=cancel_evt,
            rag_service=rag_service,
            pipeline=pipeline,
            settings=settings,
            started_ms=started_ms,
            timing_ms=timing_ms,
            answer=answer,
        ):
            yield payload

        if await request.is_disconnected():
            cancel_evt.set()
        if cancel_evt.is_set():
            yield ndjson_bytes(
                {
                    "type": "cancelled",
                    "request_id": request_id,
                    "elapsed_ms": _elapsed(started_ms),
                    "draft": answer.draft,
                    "final_partial": answer.final,
                }
            )
            return

        response = rag_service.build_query_response(
            status=QueryStatus.ANSWERED,
            conversation_id=conversation_id,
            tool_trace=list(pipeline.tool_trace),
            tool_results=pipeline.tool_results,
            draft_answer=answer.draft,
            final_answer=(answer.final if answer.final else answer.draft),
            reranked=pipeline.reranked,
        )
        update_conversation_after_query(conversation_id, effective_question, response)

        if answer.final_step_ms is not None:
            timing_ms["final_ms"] = answer.final_step_ms
        total_ms = (time.time() * 1000) - started_ms
        timing_ms["total_ms"] = float(total_ms)
        append_history(req_resolved, response, timing_ms)

        yield ndjson_bytes(
            {
                "type": "done",
                "request_id": request_id,
                "elapsed_ms": int(total_ms),
                "final_ms": _step_ms(answer.final_step_ms),
                "timing_ms": {k: (float(v) if v is not None else None) for k, v in timing_ms.items()},
                "response": jsonable_encoder(response),
            }
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Streaming query failed: %r", exc)
        yield ndjson_bytes(
            {"type": "error", "request_id": request_id, "error": str(exc), "elapsed_ms": _elapsed(started_ms)}
        )


async def stream_answer_text(
    *,
    request: Request,
    cancel_evt: threading.Event,
    rag_service: RAGService,
    pipeline: QueryPipelineExecution,
    settings: GenerationSettings,
    started_ms: int,
    timing_ms: dict[str, float],
    answer: StreamAnswerAccumulator,
) -> AsyncIterator[bytes]:
    if pipeline.planned.use_multi_ticker_briefs and pipeline.per_ticker_briefs:
        if settings.enable_refine:
            yield ndjson_bytes(
                {"type": "status", "step": "draft", "message": "Synthesizing draft answer…", "is_draft": True}
            )
            draft_result = StreamStageResult()
            async for payload in stream_text_stage(
                llm=rag_service.llm,
                request=request,
                cancel_evt=cancel_evt,
                prompt=rag_service.multi_ticker_synthesis_prompt(
                    question=pipeline.question,
                    settings=settings,
                    per_ticker_briefs=pipeline.per_ticker_briefs,
                    tool_results=pipeline.tool_results,
                ),
                temperature=rag_service._effort_temperature(settings.answering_effort),
                delta_type="draft_delta",
                allow_stream=stream_draft_enabled(),
                result=draft_result,
            ):
                yield payload
            answer.draft = draft_result.text
            if draft_result.step_ms is not None:
                timing_ms["draft_ms"] = draft_result.step_ms
            yield ndjson_bytes(
                {
                    "type": "draft_done",
                    "chars": len(answer.draft),
                    "step_ms": _step_ms(draft_result.step_ms),
                    "elapsed_ms": _elapsed(started_ms),
                }
            )

            if await request.is_disconnected():
                cancel_evt.set()
            if cancel_evt.is_set():
                return

            yield ndjson_bytes(
                {"type": "status", "step": "final", "message": "Generating final answer…", "is_draft": False}
            )
            final_result = StreamStageResult()
            async for payload in stream_text_stage(
                llm=rag_service.llm,
                request=request,
                cancel_evt=cancel_evt,
                prompt=rag_service.multi_ticker_synthesis_prompt(
                    question=pipeline.question,
                    settings=settings,
                    per_ticker_briefs=pipeline.per_ticker_briefs,
                    tool_results=pipeline.tool_results,
                    draft_answer=answer.draft,
                ),
                temperature=0.0,
                delta_type="final_delta",
                allow_stream=True,
                result=final_result,
            ):
                yield payload
            answer.final = final_result.text
            answer.final_step_ms = final_result.step_ms
            return

        yield ndjson_bytes({"type": "status", "step": "final", "message": "Synthesizing answer…"})
        final_result = StreamStageResult()
        async for payload in stream_text_stage(
            llm=rag_service.llm,
            request=request,
            cancel_evt=cancel_evt,
            prompt=rag_service.multi_ticker_synthesis_prompt(
                question=pipeline.question,
                settings=settings,
                per_ticker_briefs=pipeline.per_ticker_briefs,
                tool_results=pipeline.tool_results,
            ),
            temperature=rag_service._effort_temperature(settings.answering_effort),
            delta_type="final_delta",
            allow_stream=True,
            result=final_result,
        ):
            yield payload
        answer.final = final_result.text
        answer.final_step_ms = final_result.step_ms
        answer.draft = answer.final
        return

    if settings.enable_refine:
        yield ndjson_bytes({"type": "status", "step": "draft", "message": "Generating draft…", "is_draft": True})
        draft_result = StreamStageResult()
        async for payload in stream_text_stage(
            llm=rag_service.llm,
            request=request,
            cancel_evt=cancel_evt,
            prompt=rag_service.draft_prompt(
                pipeline.question, settings, pipeline.reranked, tool_results=pipeline.tool_results
            ),
            temperature=settings.draft_temperature,
            delta_type="draft_delta",
            allow_stream=stream_draft_enabled(),
            result=draft_result,
        ):
            yield payload
        answer.draft = draft_result.text
        if draft_result.step_ms is not None:
            timing_ms["draft_ms"] = draft_result.step_ms
        yield ndjson_bytes(
            {
                "type": "draft_done",
                "chars": len(answer.draft),
                "step_ms": _step_ms(draft_result.step_ms),
                "elapsed_ms": _elapsed(started_ms),
            }
        )

        if await request.is_disconnected():
            cancel_evt.set()
        if cancel_evt.is_set():
            return

        yield ndjson_bytes(
            {"type": "status", "step": "final", "message": "Generating final answer…", "is_draft": False}
        )
        final_result = StreamStageResult()
        async for payload in stream_text_stage(
            llm=rag_service.llm,
            request=request,
            cancel_evt=cancel_evt,
            prompt=rag_service.final_prompt(
                pipeline.question,
                settings,
                pipeline.reranked,
                draft_answer=answer.draft,
                tool_results=pipeline.tool_results,
            ),
            temperature=0.0,
            delta_type="final_delta",
            allow_stream=True,
            result=final_result,
        ):
            yield payload
        answer.final = final_result.text
        answer.final_step_ms = final_result.step_ms
    else:
        yield ndjson_bytes({"type": "status", "step": "final", "message": "Generating answer…"})
        final_result = StreamStageResult()
        async for payload in stream_text_stage(
            llm=rag_service.llm,
            request=request,
            cancel_evt=cancel_evt,
            prompt=rag_service.final_prompt(
                pipeline.question, settings, pipeline.reranked, tool_results=pipeline.tool_results
            ),
            temperature=settings.draft_temperature,
            delta_type="final_delta",
            allow_stream=True,
            result=final_result,
        ):
            yield payload
        answer.final = final_result.text
        answer.final_step_ms = final_result.step_ms
        answer.draft = answer.final


def _record_timing(*, timing_ms: dict[str, float], pipeline: QueryPipelineExecution) -> None:
    if pipeline.plan_step_ms is not None:
        timing_ms["plan_ms"] = pipeline.plan_step_ms
    if pipeline.tools_step_ms is not None:
        timing_ms["tools_ms"] = pipeline.tools_step_ms
    if pipeline.retrieve_step_ms is not None:
        timing_ms["retrieve_ms"] = pipeline.retrieve_step_ms
    if pipeline.rerank_step_ms is not None:
        timing_ms["rerank_ms"] = pipeline.rerank_step_ms
    if pipeline.brief_step_ms is not None:
        timing_ms["brief_ms"] = pipeline.brief_step_ms


def _step_ms(value: float | None) -> int | None:
    if value is None:
        return None
    return int(value)


def _elapsed(started_ms: int) -> int:
    return int(time.time() * 1000) - started_ms
