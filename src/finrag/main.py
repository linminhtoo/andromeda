import os
import tempfile
import uuid
import mimetypes
import json
import sys
import asyncio
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile, Request
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse
from loguru import logger
from pydantic import BaseModel

# from finrag.chunking import DoclingHybridChunker
from finrag.dataclasses import TopChunk
from finrag.db import RetrievalFilters
from finrag.generation_controls import (
    GenerationSettings,
    default_mode,
    list_generation_presets,
    resolve_generation_settings,
)
from finrag.llm_clients import get_llm_client
from finrag.metadata_models import chunk_metadata_from_value
from finrag.context_support import apply_context_strategy, context_builder_from_metadata
from finrag.qa import build_draft_prompt, build_refine_prompt
from finrag.retriever import CrossEncoderReranker, PostgresHybridRetriever
from finrag.streaming import (
    TextDeltaBatcher,
    iter_chat_deltas,
    ndjson_bytes,
    stream_chunks_max,
    stream_chunks_preview_chars,
    stream_draft_enabled,
)


# -------------------------------------------------------------------
# RAG service (ingestion + 2-stage QA)
# -------------------------------------------------------------------


class QueryRequest(BaseModel):
    question: str
    mode: str | None = None

    # Optional retrieval filters.
    tickers: list[str] | None = None
    filing_date_from: str | None = None
    filing_date_to: str | None = None

    # Optional overrides (use mode preset when omitted).
    top_k_retrieve: int | None = None
    top_k_rerank: int | None = None
    draft_max_tokens: int | None = None
    final_max_tokens: int | None = None
    enable_rerank: bool | None = None
    enable_refine: bool | None = None


class QueryStreamRequest(QueryRequest):
    request_id: str | None = None


class QueryResponse(BaseModel):
    draft_answer: str
    final_answer: str
    top_chunks: list[TopChunk]
    retrieved_chunks: list[TopChunk] | None = None


def _resolve_generation(req: QueryRequest) -> GenerationSettings:
    return resolve_generation_settings(
        mode=req.mode,
        top_k_retrieve=req.top_k_retrieve,
        top_k_rerank=req.top_k_rerank,
        draft_max_tokens=req.draft_max_tokens,
        final_max_tokens=req.final_max_tokens,
        enable_rerank=req.enable_rerank,
        enable_refine=req.enable_refine,
    )


def _request_with_resolved_settings(req: QueryRequest, settings: GenerationSettings) -> QueryRequest:
    return QueryRequest(
        question=req.question,
        mode=settings.mode,
        tickers=req.tickers,
        filing_date_from=req.filing_date_from,
        filing_date_to=req.filing_date_to,
        top_k_retrieve=settings.top_k_retrieve,
        top_k_rerank=settings.top_k_rerank,
        draft_max_tokens=settings.draft_max_tokens,
        final_max_tokens=settings.final_max_tokens,
        enable_rerank=settings.enable_rerank,
        enable_refine=settings.enable_refine,
    )


def _setup_logging(project_root: Path) -> Path:
    logs_dir = project_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    log_path = logs_dir / f"main_app_{ts}.log"

    logger.remove()
    logger.add(sys.stderr, level="INFO")
    logger.add(str(log_path), level="DEBUG")
    return log_path


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _llm_provider_name() -> str:
    return (os.getenv("LLM_PROVIDER") or "openai").strip().lower()


def _llm_chat_model() -> str | None:
    provider = _llm_provider_name()
    if provider == "openai":
        return (os.getenv("OPENAI_CHAT_MODEL") or os.getenv("CHAT_MODEL") or "").strip() or None
    if provider == "mistral":
        return (os.getenv("MISTRAL_CHAT_MODEL") or os.getenv("CHAT_MODEL") or "").strip() or None
    return (os.getenv("CHAT_MODEL") or "").strip() or None


def _llm_embed_model() -> str | None:
    provider = _llm_provider_name()
    if provider == "openai":
        return (os.getenv("OPENAI_EMBED_MODEL") or os.getenv("EMBED_MODEL") or "").strip() or None
    if provider == "mistral":
        return (os.getenv("MISTRAL_EMBED_MODEL") or os.getenv("EMBED_MODEL") or "").strip() or None
    return (os.getenv("EMBED_MODEL") or "").strip() or None


def _llm_for_embeddings():
    provider = os.getenv("LLM_PROVIDER")
    if _llm_provider_name() == "openai":
        return get_llm_client(
            provider=provider,
            base_url=(os.getenv("OPENAI_EMBED_BASE_URL") or None),
            embed_model=_llm_embed_model() or "text-embedding-3-large",
        )
    embed_model = _llm_embed_model()
    return (
        get_llm_client(provider=provider, embed_model=embed_model) if embed_model else get_llm_client(provider=provider)
    )


def _llm_for_chat():
    provider = os.getenv("LLM_PROVIDER")
    langsmith_trace = False
    if os.environ.get("LANGSMITH_TRACING", "false").lower() == "true":
        langsmith_trace = True

    if _llm_provider_name() == "openai":
        return get_llm_client(
            provider=provider,
            base_url=(os.getenv("OPENAI_CHAT_BASE_URL") or None),
            chat_model=_llm_chat_model() or "gpt-4o-mini",
            langsmith_trace=langsmith_trace,
        )

    if langsmith_trace:
        logger.warning("LANGSMITH_TRACING is only supported for OpenAI provider at this time.")
    chat_model = _llm_chat_model()
    return get_llm_client(provider=provider, chat_model=chat_model) if chat_model else get_llm_client(provider=provider)


def _context_config() -> tuple[str, int, str]:
    strategy = os.getenv("CONTEXT_STRATEGY", "none").strip().lower()
    window_raw = os.getenv("CONTEXT_WINDOW", "1")
    try:
        window = int(window_raw)
    except ValueError as exc:
        raise RuntimeError("CONTEXT_WINDOW must be an integer") from exc
    metadata_key = os.getenv("CONTEXT_METADATA_KEY", "retrieval_context").strip() or "retrieval_context"
    return strategy, window, metadata_key


def postgres_dsn() -> str:
    """
    Resolve PostgreSQL connection string from environment.

    Returns
    -------
    str
        Database connection string.
    """

    dsn = (os.getenv("POSTGRES_DSN") or os.getenv("DATABASE_URL") or "").strip()
    if not dsn:
        raise RuntimeError("Missing POSTGRES_DSN (or DATABASE_URL).")
    return dsn


def build_retriever() -> PostgresHybridRetriever:
    """
    Build PostgreSQL retriever from environment configuration.

    Returns
    -------
    PostgresHybridRetriever
        Configured retriever instance.
    """

    _, _, context_key = _context_config()
    retriever = PostgresHybridRetriever(
        llm_client=_llm_for_embeddings(),
        dsn=postgres_dsn(),
        context_builder=context_builder_from_metadata(key=context_key),
        retrieval_context_key=context_key,
    )
    logger.info("Using PostgreSQL retriever")
    return retriever


def build_reranker() -> CrossEncoderReranker:
    reranker_model = os.getenv("RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2").strip()
    logger.info(f"Using reranker model: {reranker_model}")
    return CrossEncoderReranker(model_name=reranker_model)


class RAGService:
    def __init__(self):
        self.llm = _llm_for_chat()
        logger.info(f"Using LLM chat model: {self.llm.chat_model}")
        self.retriever = build_retriever()
        self.reranker = build_reranker()
        self._context_strategy, self._context_window, self._context_key = _context_config()

        # Two chunkers: with and without Mistral OCR
        # self.chunker_ocr = DoclingHybridChunker(use_mistral_ocr=True)
        # self.chunker_pdf = DoclingHybridChunker(use_mistral_ocr=False)

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

        return out or None

    def _serialize_top_chunks(self, reranked) -> list[TopChunk]:
        retrieval_text_key = getattr(self.retriever, "retrieval_text_key", "retrieval_text")
        out: list[TopChunk] = []
        for sc in reranked:
            parsed = chunk_metadata_from_value(sc.chunk.metadata)
            if retrieval_text_key == "retrieval_text":
                raw_text = parsed.retrieval_text
            else:
                raw_text = parsed.context_for_key(retrieval_text_key)
            display_text = str(raw_text or sc.chunk.text or "")
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
                    context=context_value,
                    metadata=self._chunk_metadata_for_ui(parsed.to_dict()),
                )
            )
        return out

    def ingest_document(self, path: str, use_mistral_ocr: bool) -> str:
        """
        FIXME: docstring is outdated.

        Ingest a single PDF at `path` using either:
        - Mistral OCR -> Markdown -> Docling -> HybridChunker
        - Direct Docling PDF parsing -> HybridChunker
        """
        raise RuntimeError("On-the-fly ingestion is disabled for now. Use batch ingestion script.")

        doc_id = str(uuid.uuid4())
        chunker = self.chunker_ocr if use_mistral_ocr else self.chunker_pdf

        # TODO: add logic from `process_html_to_markdown.py`

        docling_chunks = chunker.chunk_document(path, doc_id=doc_id)
        apply_context_strategy(
            docling_chunks,
            strategy=self._context_strategy,
            neighbor_window=self._context_window,
            metadata_key=self._context_key,
            llm_for_context=self.llm,
        )
        self.retriever.index(docling_chunks)
        return doc_id

    def answer_question(
        self,
        question: str,
        settings: GenerationSettings,
        *,
        tickers: list[str] | None = None,
        filing_date_from: str | None = None,
        filing_date_to: str | None = None,
        include_retrieved_chunks: bool = False,
    ) -> QueryResponse:
        """
        
        TODO's
        ------
        - should we infer filters from question?
            i.e. build_filters() could be a tool called by the LLM if it deems necessary
        - system should ask clarifying questions if question is underspecified
            * AND/OR add logic to infer those details
                e.g. "latest earnings report" -> map to most recent filing date filter
        - system should refuse to answer if:
            * retriever / reranker scores are too low - even before LLM gets to see them
            * question is out of scope / harmful (DONE)
            * final chunks do not contain required context (DONE)
        """
        filters: RetrievalFilters = self.retriever.build_filters(
            tickers=tickers, filing_date_from=filing_date_from, filing_date_to=filing_date_to
        )

        hybrid = self.retriever.retrieve_hybrid(
            question,
            top_k_semantic=settings.top_k_retrieve,
            top_k_bm25=settings.top_k_retrieve,
            top_k_final=settings.top_k_retrieve,
            filters=filters,
        )

        if settings.enable_rerank:
            reranked = self.reranker.rerank(
                question, hybrid, top_k=settings.top_k_rerank, candidate_text_provider=self.retriever.text_for_rerank
            )
        else:
            reranked = hybrid[: settings.top_k_rerank]

        draft_prompt = build_draft_prompt(
            question, reranked, draft_max_tokens=settings.draft_max_tokens, answer_style=settings.answer_style
        )
        draft = self.llm.chat(draft_prompt, temperature=settings.draft_temperature)  # type: ignore[arg-type]

        final = draft
        if settings.enable_refine:
            refine_prompt = build_refine_prompt(
                question,
                draft,
                reranked,
                final_max_tokens=settings.final_max_tokens,
                answer_style=settings.answer_style,
            )
            final = self.llm.chat(refine_prompt, temperature=0.0)  # type: ignore[arg-type]

        top_chunks = self._serialize_top_chunks(reranked)
        retrieved_chunks = self._serialize_top_chunks(hybrid) if include_retrieved_chunks else None
        return QueryResponse(
            draft_answer=draft, final_answer=final, top_chunks=top_chunks, retrieved_chunks=retrieved_chunks
        )


# -------------------------------------------------------------------
# FastAPI wiring
# -------------------------------------------------------------------

project_root = Path(__file__).resolve().parents[2]
log_path = _setup_logging(project_root)
logger.debug("Project root: %s", project_root)
logger.info("Starting RAG service; logs at: %s", log_path)

app = FastAPI(title="Andromeda RAG (PostgreSQL)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # lock this down for real deployments
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Eval review UI (labels + retrieval inspection).
try:
    from finrag.review_ui import router as review_router

    app.include_router(review_router)
except Exception as exc:  # noqa: BLE001
    # Avoid taking down the main app if optional review UI files are missing.
    logger.warning(f"Review UI not available: {exc}")

_RAG_SERVICE_LOCK = threading.Lock()
_RAG_SERVICE: "RAGService | None" = None


def get_rag_service() -> "RAGService":
    """
    Lazily construct the global RAG service.

    This keeps module import side-effects light (important for unit tests and
    for tooling that imports `finrag.main` without intending to boot the full
    retrieval + LLM stack).
    """

    global _RAG_SERVICE
    if _RAG_SERVICE is not None:
        return _RAG_SERVICE
    with _RAG_SERVICE_LOCK:
        if _RAG_SERVICE is None:
            _RAG_SERVICE = RAGService()
        return _RAG_SERVICE


_CANCEL_LOCK = threading.Lock()
_CANCEL_EVENTS: dict[str, threading.Event] = {}


def _register_cancel_event(request_id: str) -> threading.Event:
    with _CANCEL_LOCK:
        evt = _CANCEL_EVENTS.get(request_id)
        if evt is None:
            evt = threading.Event()
            _CANCEL_EVENTS[request_id] = evt
        return evt


def _cancel_request(request_id: str) -> bool:
    with _CANCEL_LOCK:
        evt = _CANCEL_EVENTS.get(request_id)
    if evt is None:
        return False
    evt.set()
    return True


def _cleanup_cancel_event(request_id: str) -> None:
    with _CANCEL_LOCK:
        _CANCEL_EVENTS.pop(request_id, None)


class CancelRequest(BaseModel):
    request_id: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/generation_presets")
def generation_presets():
    return {"default_mode": default_mode(), "presets": [p.to_public_dict() for p in list_generation_presets()]}


@app.post("/ingest")
async def ingest_pdf(file: UploadFile = File(...), use_mistral_ocr: bool = Form(False)):
    # Save uploaded file to a temp path
    filename = file.filename
    if filename is None:
        raise ValueError("Uploaded file must have a filename")
    suffix = os.path.splitext(filename)[-1] or ".pdf"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        contents = await file.read()
        tmp.write(contents)
        tmp_path = tmp.name

    try:
        doc_id = get_rag_service().ingest_document(tmp_path, use_mistral_ocr=use_mistral_ocr)
    finally:
        # optional: keep PDFs for audit; for now, delete
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    return {"doc_id": doc_id}


@app.post("/query")
async def query_docs(req: QueryRequest):
    # TODO: explore adding support for multi-turn Q&A
    settings = _resolve_generation(req)
    req_resolved = _request_with_resolved_settings(req, settings)
    result = get_rag_service().answer_question(
        question=req.question,
        settings=settings,
        tickers=req.tickers,
        filing_date_from=req.filing_date_from,
        filing_date_to=req.filing_date_to,
    )
    _append_history(req=req_resolved, res=result)
    return result


def _stream_chunk_dict(sc, *, preview_chars: int, text_chars: int) -> dict:
    parsed = chunk_metadata_from_value(sc.chunk.metadata)
    base_text = parsed.retrieval_text or sc.chunk.text or ""
    text = str(base_text).strip()
    preview = text[:preview_chars] if preview_chars > 0 else ""
    chunk_text = text[:text_chars] if text_chars > 0 else ""
    return {
        "chunk_id": sc.chunk.id,
        "doc_id": sc.chunk.doc_id,
        "page_no": sc.chunk.page_no,
        "headings": sc.chunk.headings,
        "score": sc.score,
        "preview": preview,
        "source": sc.chunk.source,
        "text": chunk_text,
        "metadata": RAGService._chunk_metadata_for_ui(sc.chunk.metadata),
    }


@app.post("/cancel")
def cancel(req: CancelRequest):
    ok = _cancel_request((req.request_id or "").strip())
    return {"status": "ok" if ok else "not_found"}


# TODO: duplicate logic with non-streaming / rethink structure
# everytime we make a change to the answering logic, we need to update both places, not good
@app.post("/query_stream")
async def query_docs_stream(req: QueryStreamRequest, request: Request):
    rag_service = get_rag_service()
    request_id = (req.request_id or "").strip() or str(uuid.uuid4())
    base_req = QueryRequest(**req.model_dump(exclude={"request_id"}))
    settings = _resolve_generation(base_req)
    req_resolved = _request_with_resolved_settings(base_req, settings)
    cancel_evt = _register_cancel_event(request_id)
    started_ms = int(time.time() * 1000)
    filters: RetrievalFilters = rag_service.retriever.build_filters(
        tickers=req.tickers, filing_date_from=req.filing_date_from, filing_date_to=req.filing_date_to
    )

    preview_chars = max(0, stream_chunks_preview_chars())
    max_chunks = max(0, stream_chunks_max())
    try:
        text_chars = int((os.getenv("FINRAG_STREAM_CHUNKS_TEXT_CHARS", "1000") or "1000").strip())
    except ValueError:
        text_chars = 1000
    text_chars = max(0, text_chars)

    async def gen():
        full_draft = ""
        full_final = ""
        timing_ms: dict[str, float] = {}
        retrieve_step_ms: float | None = None
        rerank_step_ms: float | None = None
        draft_step_ms: float | None = None
        final_step_ms: float | None = None

        def is_cancelled() -> bool:
            return cancel_evt.is_set()

        def set_cancelled() -> None:
            cancel_evt.set()

        try:
            yield ndjson_bytes({"type": "start", "request_id": request_id})

            yield ndjson_bytes({"type": "status", "step": "retrieve", "message": "Retrieving chunks…"})
            t0 = time.perf_counter()
            hybrid = await asyncio.to_thread(
                rag_service.retriever.retrieve_hybrid,
                req.question,
                top_k_semantic=settings.top_k_retrieve,
                top_k_bm25=settings.top_k_retrieve,
                top_k_final=settings.top_k_retrieve,
                filters=filters,
            )
            retrieve_step_ms = (time.perf_counter() - t0) * 1000.0

            if await request.is_disconnected():
                set_cancelled()
            if is_cancelled():
                yield ndjson_bytes(
                    {"type": "cancelled", "request_id": request_id, "elapsed_ms": int(time.time() * 1000) - started_ms}
                )
                return

            retrieved_payload = [
                _stream_chunk_dict(sc, preview_chars=preview_chars, text_chars=text_chars) for sc in hybrid
            ]
            if max_chunks:
                retrieved_payload = retrieved_payload[:max_chunks]
            if retrieve_step_ms is not None:
                timing_ms["retrieve_ms"] = retrieve_step_ms
            yield ndjson_bytes(
                {
                    "type": "retrieved",
                    "count": len(hybrid),
                    "chunks": retrieved_payload,
                    "step_ms": int(retrieve_step_ms) if retrieve_step_ms is not None else None,
                    "elapsed_ms": int(time.time() * 1000) - started_ms,
                }
            )

            yield ndjson_bytes(
                {
                    "type": "status",
                    "step": "rerank",
                    "message": ("Reranking chunks…" if settings.enable_rerank else "Skipping rerank (mode preset)…"),
                }
            )
            t0 = time.perf_counter()
            if settings.enable_rerank:
                reranked = await asyncio.to_thread(
                    rag_service.reranker.rerank,
                    req.question,
                    hybrid,
                    top_k=settings.top_k_rerank,
                    candidate_text_provider=rag_service.retriever.text_for_rerank,
                )
            else:
                reranked = hybrid[: settings.top_k_rerank]
            rerank_step_ms = (time.perf_counter() - t0) * 1000.0

            if await request.is_disconnected():
                set_cancelled()
            if is_cancelled():
                yield ndjson_bytes(
                    {"type": "cancelled", "request_id": request_id, "elapsed_ms": int(time.time() * 1000) - started_ms}
                )
                return

            reranked_payload = [
                _stream_chunk_dict(sc, preview_chars=preview_chars, text_chars=text_chars) for sc in reranked
            ]
            if rerank_step_ms is not None:
                timing_ms["rerank_ms"] = rerank_step_ms
            yield ndjson_bytes(
                {
                    "type": "reranked",
                    "count": len(reranked),
                    "chunks": reranked_payload,
                    "step_ms": int(rerank_step_ms) if rerank_step_ms is not None else None,
                    "elapsed_ms": int(time.time() * 1000) - started_ms,
                }
            )

            # TODO: simplify this if-else. duplicated code for the draft answer streaming.
            if settings.enable_refine:
                yield ndjson_bytes(
                    {"type": "status", "step": "draft", "message": "Generating draft…", "is_draft": True}
                )
                draft_prompt = build_draft_prompt(
                    req.question,
                    reranked,
                    draft_max_tokens=settings.draft_max_tokens,
                    answer_style=settings.answer_style,
                )
                t0 = time.monotonic()
                if stream_draft_enabled():
                    batcher = TextDeltaBatcher.from_env()
                    async for delta in iter_chat_deltas(
                        rag_service.llm,
                        draft_prompt,  # type: ignore[arg-type]
                        temperature=settings.draft_temperature,
                        is_cancelled=is_cancelled,
                        set_cancelled=set_cancelled,
                        is_disconnected=request.is_disconnected,
                    ):
                        full_draft += delta
                        batcher.add(delta)
                        out = batcher.pop_ready()
                        if out:
                            yield ndjson_bytes({"type": "draft_delta", "delta": out})
                        if is_cancelled():
                            break
                    out = batcher.pop_all()
                    if out:
                        yield ndjson_bytes({"type": "draft_delta", "delta": out})
                else:
                    full_draft = await asyncio.to_thread(rag_service.llm.chat, draft_prompt, settings.draft_temperature)
                draft_step_ms = (time.monotonic() - t0) * 1000.0

                if draft_step_ms is not None:
                    timing_ms["draft_ms"] = draft_step_ms
                yield ndjson_bytes(
                    {
                        "type": "draft_done",
                        "chars": len(full_draft),
                        "step_ms": int(draft_step_ms) if draft_step_ms is not None else None,
                        "elapsed_ms": int(time.time() * 1000) - started_ms,
                    }
                )

                if await request.is_disconnected():
                    set_cancelled()
                if is_cancelled():
                    yield ndjson_bytes(
                        {
                            "type": "cancelled",
                            "request_id": request_id,
                            "elapsed_ms": int(time.time() * 1000) - started_ms,
                        }
                    )
                    return

                yield ndjson_bytes(
                    {"type": "status", "step": "final", "message": "Generating final answer…", "is_draft": False}
                )
                refine_prompt = build_refine_prompt(
                    req.question,
                    full_draft,
                    reranked,
                    final_max_tokens=settings.final_max_tokens,
                    answer_style=settings.answer_style,
                )
                t0 = time.monotonic()
                batcher = TextDeltaBatcher.from_env()
                async for delta in iter_chat_deltas(
                    rag_service.llm,
                    refine_prompt,  # type: ignore[arg-type]
                    temperature=0.0,
                    is_cancelled=is_cancelled,
                    set_cancelled=set_cancelled,
                    is_disconnected=request.is_disconnected,
                ):
                    full_final += delta
                    batcher.add(delta)
                    out = batcher.pop_ready()
                    if out:
                        yield ndjson_bytes({"type": "final_delta", "delta": out})
                    if is_cancelled():
                        break
                out = batcher.pop_all()
                if out:
                    yield ndjson_bytes({"type": "final_delta", "delta": out})
                final_step_ms = (time.monotonic() - t0) * 1000.0
            else:
                yield ndjson_bytes({"type": "status", "step": "final", "message": "Generating answer…"})
                answer_prompt = build_draft_prompt(
                    req.question,
                    reranked,
                    draft_max_tokens=settings.draft_max_tokens,
                    answer_style=settings.answer_style,
                )
                batcher = TextDeltaBatcher.from_env()
                t0 = time.monotonic()
                async for delta in iter_chat_deltas(
                    rag_service.llm,
                    answer_prompt,  # type: ignore[arg-type]
                    temperature=settings.draft_temperature,
                    is_cancelled=is_cancelled,
                    set_cancelled=set_cancelled,
                    is_disconnected=request.is_disconnected,
                ):
                    full_final += delta
                    batcher.add(delta)
                    out = batcher.pop_ready()
                    if out:
                        yield ndjson_bytes({"type": "final_delta", "delta": out})
                    if is_cancelled():
                        break
                out = batcher.pop_all()
                if out:
                    yield ndjson_bytes({"type": "final_delta", "delta": out})
                final_step_ms = (time.monotonic() - t0) * 1000.0
                full_draft = full_final

            if await request.is_disconnected():
                set_cancelled()
            if is_cancelled():
                yield ndjson_bytes(
                    {
                        "type": "cancelled",
                        "request_id": request_id,
                        "elapsed_ms": int(time.time() * 1000) - started_ms,
                        "draft": full_draft,
                        "final_partial": full_final,
                    }
                )
                return

            res = QueryResponse(
                draft_answer=full_draft,
                final_answer=(full_final if full_final else full_draft),
                top_chunks=rag_service._serialize_top_chunks(reranked),
            )
            _append_history(req=req_resolved, res=res)

            if final_step_ms is not None:
                timing_ms["final_ms"] = final_step_ms
            total_ms = (time.time() * 1000) - started_ms
            timing_ms["total_ms"] = float(total_ms)

            yield ndjson_bytes(
                {
                    "type": "done",
                    "request_id": request_id,
                    "elapsed_ms": int(total_ms),
                    "final_ms": int(final_step_ms) if final_step_ms is not None else None,
                    "timing_ms": {k: (float(v) if v is not None else None) for k, v in timing_ms.items()},
                    "response": jsonable_encoder(res),
                }
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Streaming query failed: %r", exc)
            yield ndjson_bytes(
                {
                    "type": "error",
                    "request_id": request_id,
                    "error": str(exc),
                    "elapsed_ms": int(time.time() * 1000) - started_ms,
                }
            )
        finally:
            _cleanup_cancel_event(request_id)

    return StreamingResponse(gen(), media_type="application/x-ndjson")


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _source_roots() -> list[Path]:
    raw = os.getenv("SOURCE_ROOTS")
    if raw:
        parts = [p.strip() for p in raw.split(os.pathsep) if p.strip()]
        return [Path(p).expanduser().resolve() for p in parts]
    root = _project_root()
    return [root, root / "data"]


def _resolve_local_source(path: str) -> Path:
    path = (path or "").strip()
    if not path:
        raise HTTPException(status_code=400, detail="Missing `path`")

    p = Path(os.path.expanduser(path))
    if not p.is_absolute():
        p = (_project_root() / p).resolve()
    else:
        p = p.resolve()

    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {p}")

    allowed = _source_roots()
    if not any(p == root or p.is_relative_to(root) for root in allowed):
        raise HTTPException(
            status_code=403,
            detail=("Path is outside SOURCE_ROOTS; set SOURCE_ROOTS to a colon-separated allowlist of directories."),
        )

    return p


@app.get("/source")
def get_source(path: str = Query(..., description="Local file path or URL")):
    path = (path or "").strip()
    if path.startswith(("http://", "https://")):
        return RedirectResponse(url=path)
    p = _resolve_local_source(path)
    media_type, _enc = mimetypes.guess_type(str(p))
    return FileResponse(
        path=p, media_type=media_type or "application/octet-stream", filename=p.name, content_disposition_type="inline"
    )


def _read_text_file(path: Path, *, max_bytes: int) -> str:
    if max_bytes <= 0:
        raise HTTPException(status_code=400, detail="SOURCE_TEXT_MAX_BYTES must be > 0")
    size = path.stat().st_size
    if size > max_bytes:
        raise HTTPException(status_code=413, detail=f"File too large ({size} bytes); max is {max_bytes} bytes")
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


@app.get("/source_text")
def get_source_text(path: str = Query(..., description="Local markdown/text file path")):
    p = _resolve_local_source(path)
    suffix = p.suffix.lower()
    if suffix not in {".md", ".markdown", ".txt"}:
        raise HTTPException(status_code=415, detail="Only .md/.markdown/.txt are supported for inline text viewing")

    max_bytes_raw = os.getenv("SOURCE_TEXT_MAX_BYTES", "5000000").strip()
    try:
        max_bytes = int(max_bytes_raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="SOURCE_TEXT_MAX_BYTES must be an integer") from exc

    return {"path": str(p), "text": _read_text_file(p, max_bytes=max_bytes)}


@dataclass
class IngestedCompaniesCache:
    path: str | None = None
    mtime_ns: int | None = None
    use_yahoo: bool | None = None
    items: list[dict[str, str]] | None = None


_INGESTED_COMPANIES_CACHE = IngestedCompaniesCache()
_YAHOO_COMPANY_RESOLVER: object | None = None


def _doc_index_path() -> Path | None:
    raw = os.getenv("FINRAG_DOC_INDEX_PATH") or os.getenv("DOC_INDEX_PATH") or ""
    raw = raw.strip()
    if not raw:
        return None
    p = Path(os.path.expanduser(raw))
    if not p.is_absolute():
        p = (_project_root() / p).resolve()
    else:
        p = p.resolve()
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail=f"doc_index.jsonl not found: {p}")
    return p


def _ticker_from_relpath(relpath: str) -> str:
    base = Path(relpath or "").name
    if "_" in base:
        return base.split("_", 1)[0].strip().upper()
    stem = Path(base).stem
    return stem.strip().upper()


def _strip_md_emphasis(s: str) -> str:
    s = s.replace("**", "").replace("__", "").replace("*", "").replace("_", "")
    return " ".join(s.split())


def _clean_company_heading(s: str) -> str:
    s = " ".join((s or "").split())
    if not s:
        return ""
    lowered = s.lower()
    # Remove common "noise" suffixes.
    for token in (" table of contents", " index to", " index of", " index"):
        if lowered.endswith(token):
            s = s[: -len(token)].strip()
            lowered = s.lower()
    if " index to " in lowered:
        s = s[: lowered.index(" index to ")].strip()
        lowered = s.lower()
    if " table of contents" in lowered and lowered.endswith(" table of contents"):
        s = s[: lowered.index(" table of contents")].strip()
        lowered = s.lower()
    return " ".join(s.split())


def _company_name_from_markdown(path: Path) -> str | None:
    try:
        text = _read_text_file(path, max_bytes=200_000)
    except Exception:  # noqa: BLE001 - best-effort extraction
        return None

    best: tuple[int, str] | None = None
    for line in text.splitlines()[:80]:
        ln = line.strip()
        if not ln.startswith("#"):
            continue
        level = len(ln) - len(ln.lstrip("#"))
        ln = ln.lstrip("#").strip()
        if not ln:
            continue
        ln = _strip_md_emphasis(ln)
        ln = _clean_company_heading(ln)
        if not ln:
            continue

        lowered = ln.lower()
        if lowered in {"table of contents", "index", "index to", "index of"}:
            continue
        if "table of contents" in lowered:
            continue

        score = 0
        if level == 1:
            score += 3
        if " form " in lowered or lowered.endswith(" form") or lowered.startswith("form "):
            score += 6
            parts = ln.split(" Form ", 1)
            if len(parts) == 2 and parts[0].strip():
                ln = parts[0].strip()
            else:
                parts = ln.split(" FORM ", 1)
                if len(parts) == 2 and parts[0].strip():
                    ln = parts[0].strip()
        if any(t in lowered for t in (" corporation", " corp", " inc", " ltd", " limited", " plc", " company")):
            score += 2
        if " index" in lowered:
            score -= 4

        ln = _clean_company_heading(ln)
        if not ln:
            continue
        if best is None or score > best[0]:
            best = (score, ln)

    if best and best[1]:
        return best[1]
    return None


@dataclass(frozen=True)
class DocIndexSourceRow:
    relpath: str
    source: str

    @classmethod
    def from_json_obj(cls, value: object) -> "DocIndexSourceRow | None":
        if not isinstance(value, dict):
            return None
        relpath_value = value["relpath"] if "relpath" in value else ""
        source_value = value["source"] if "source" in value else ""
        relpath = relpath_value if isinstance(relpath_value, str) else str(relpath_value)
        source = source_value if isinstance(source_value, str) else str(source_value)
        return cls(relpath=relpath, source=source)


def _read_ingested_companies(doc_index_path: Path) -> list[dict[str, str]]:
    def _looks_like_junk_company_name(name: str) -> bool:
        s = " ".join((name or "").split()).strip()
        if not s:
            return True
        low = s.lower()
        if low in {"table of contents", "index", "index to", "index of"}:
            return True
        if "table of contents" in low:
            return True
        if low.startswith("index ") or " index to " in low:
            return True
        return False

    def _resolve_company_name(ticker: str, md_path: Path) -> str:
        use_yahoo = _env_bool("FINRAG_INGESTED_COMPANIES_USE_YAHOO", default=True)
        if use_yahoo:
            global _YAHOO_COMPANY_RESOLVER  # noqa: PLW0603
            if _YAHOO_COMPANY_RESOLVER is None:
                try:
                    from finrag.chunk_postprocess import YahooFinanceCompanyNameResolver

                    _YAHOO_COMPANY_RESOLVER = YahooFinanceCompanyNameResolver()
                except Exception:  # noqa: BLE001 - best-effort resolver
                    _YAHOO_COMPANY_RESOLVER = False
            if _YAHOO_COMPANY_RESOLVER is not False:
                try:
                    name = _YAHOO_COMPANY_RESOLVER.resolve(ticker=ticker, cik=None)  # type: ignore[union-attr]
                except Exception:  # noqa: BLE001 - best-effort resolver
                    name = None
                if isinstance(name, str) and name.strip() and not _looks_like_junk_company_name(name):
                    return name.strip()

        md_name = _company_name_from_markdown(md_path)
        if isinstance(md_name, str) and md_name.strip() and not _looks_like_junk_company_name(md_name):
            return md_name.strip()
        return ticker

    by_ticker: dict[str, Path] = {}
    with doc_index_path.open("r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            row = DocIndexSourceRow.from_json_obj(obj)
            if row is None:
                continue
            ticker = _ticker_from_relpath(row.relpath or row.source)
            if not ticker or ticker in by_ticker:
                continue
            if not row.source:
                continue
            by_ticker[ticker] = Path(row.source)

    items: list[dict[str, str]] = []
    for ticker, md_path in by_ticker.items():
        company = _resolve_company_name(ticker, md_path)
        items.append({"ticker": ticker, "company": company})

    items.sort(key=lambda item: item["ticker"])
    return items


@app.get("/ingested_companies")
def ingested_companies():
    """
    Return the set of tickers (and best-effort company names) available in the currently ingested dataset.

    Configure by setting FINRAG_DOC_INDEX_PATH (preferred) or DOC_INDEX_PATH.
    """

    path = _doc_index_path()
    if path is None:
        return {"items": [], "count": 0, "path": None, "warning": "FINRAG_DOC_INDEX_PATH not set"}

    mtime_ns = path.stat().st_mtime_ns
    cached_path = _INGESTED_COMPANIES_CACHE.path
    cached_mtime = _INGESTED_COMPANIES_CACHE.mtime_ns
    cached_use_yahoo = _INGESTED_COMPANIES_CACHE.use_yahoo
    cached_items = _INGESTED_COMPANIES_CACHE.items
    use_yahoo = _env_bool("FINRAG_INGESTED_COMPANIES_USE_YAHOO", default=True)
    if (
        cached_path == str(path)
        and cached_mtime == mtime_ns
        and cached_use_yahoo == use_yahoo
        and isinstance(cached_items, list)
    ):
        return {"items": cached_items, "count": len(cached_items), "path": str(path)}

    items = _read_ingested_companies(path)
    _INGESTED_COMPANIES_CACHE.path = str(path)
    _INGESTED_COMPANIES_CACHE.mtime_ns = mtime_ns
    _INGESTED_COMPANIES_CACHE.use_yahoo = use_yahoo
    _INGESTED_COMPANIES_CACHE.items = items
    return {"items": items, "count": len(items), "path": str(path)}


class HistoryEntry(BaseModel):
    id: str
    created_at: str
    request: QueryRequest
    response: QueryResponse


def _history_path() -> Path:
    raw = os.getenv("HISTORY_PATH")
    if raw and raw.strip():
        return Path(os.path.expanduser(raw.strip())).resolve()
    return (_project_root() / "data" / "qa_history.jsonl").resolve()


def _append_history(*, req: QueryRequest, res: QueryResponse) -> None:
    if _env_bool("DISABLE_HISTORY", default=False):
        return
    entry = HistoryEntry(
        id=str(uuid.uuid4()), created_at=datetime.now(timezone.utc).isoformat(), request=req, response=res
    )
    path = _history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(jsonable_encoder(entry), ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001 - history should never break /query
        logger.warning("Failed to write history to %s: %r", path, exc)


def _read_history(*, limit: int = 50, summary: bool = False) -> list[dict]:
    limit = max(0, int(limit))
    path = _history_path()
    if limit == 0 or not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as f:
            lines = [ln for ln in (line.strip() for line in f) if ln]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to read history from %s: %r", path, exc)
        return []

    out: list[dict] = []
    for line in reversed(lines[-limit:]):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        try:
            entry = HistoryEntry.model_validate(payload)
        except Exception:  # noqa: BLE001
            continue
        if not summary:
            out.append(entry.model_dump())
            continue

        # Keep the list lightweight for the UI: omit large answer text and chunks.
        out.append(
            {
                "id": entry.id,
                "created_at": entry.created_at,
                "request": {"question": entry.request.question, "mode": entry.request.mode},
                "response": {"top_chunks_count": len(entry.response.top_chunks)},
            }
        )
    return out


@app.get("/history")
def history(limit: int = 50, summary: bool = False):
    return {"items": _read_history(limit=limit, summary=summary), "path": str(_history_path())}


@app.get("/history_entry")
def history_entry(id: str = Query(..., description="History entry id")):
    want = (id or "").strip()
    if not want:
        raise HTTPException(status_code=400, detail="Missing `id`")

    path = _history_path()
    if not path.exists():
        raise HTTPException(status_code=404, detail="History file not found")

    try:
        with path.open("r", encoding="utf-8") as f:
            lines = [ln for ln in (line.strip() for line in f) if ln]
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to read history: {exc}") from exc

    for line in reversed(lines):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        try:
            entry = HistoryEntry.model_validate(payload)
        except Exception:  # noqa: BLE001
            continue
        if entry.id == want:
            return entry.model_dump()

    raise HTTPException(status_code=404, detail="History entry not found")


@app.delete("/history")
def clear_history():
    path = _history_path()
    if path.exists():
        path.unlink()
    return {"status": "ok", "path": str(path)}


# -------------------------------------------------------------------
# Simple HTML frontend
# -------------------------------------------------------------------

HTML_PATH = Path(__file__).parent / "static" / "index.html"


@app.get("/", response_class=HTMLResponse)
def index():
    # Read on request so frontend edits don't require a server restart.
    return HTML_PATH.read_text(encoding="utf-8")
