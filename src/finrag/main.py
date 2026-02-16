import os
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger
from pydantic import BaseModel, Field

from finrag.generation_controls import (
    GenerationSettings,
    default_mode,
    list_generation_presets,
    resolve_generation_settings,
)
from finrag.ingested_companies import IngestedCompaniesService
from finrag.ingestion_jobs import TickerIngestionJobManager, normalize_ticker
from finrag.history_store import QueryHistoryStore
from finrag.query_conversation import ConversationStore
from finrag.query_runtime import QueryRequest, QueryResponse, QueryStreamRequest, RAGService, ToolTraceEvent
from finrag.query_streaming import StreamCancelRegistry, run_query_stream
from finrag.runtime_builders import (
    build_reranker,
    build_retriever,
    build_ticker_ingestion_config,
    context_config,
    llm_for_chat,
    setup_logging,
)
from finrag.source_access import read_text_file, resolve_local_source, source_response


# -------------------------------------------------------------------
# RAG service (ingestion + 2-stage QA)
# -------------------------------------------------------------------


class TickerIngestRequest(BaseModel):
    ticker: str | None = None
    tickers: list[str] | None = None
    per_company: int = Field(default=8, ge=1, le=25)

    def requested_tickers(self) -> list[str]:
        """
        Return user-requested ticker symbols in insertion order.
        """

        out: list[str] = []
        if self.ticker is not None and self.ticker.strip():
            out.append(self.ticker)
        if self.tickers is not None:
            for item in self.tickers:
                text = str(item or "").strip()
                if text:
                    out.append(text)
        return out


class TickerIngestJobStatus(BaseModel):
    job_id: str
    tickers: list[str]
    per_company: int
    status: str
    stage: str
    message: str
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    run_root: str | None = None
    log_path: str | None = None
    doc_index_path: str | None = None


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
        conversation_id=req.conversation_id,
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


# -------------------------------------------------------------------
# FastAPI wiring
# -------------------------------------------------------------------

project_root = Path(__file__).resolve().parents[2]
log_path = setup_logging(project_root=project_root)
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

static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")

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
            _, _, context_key = context_config()
            _RAG_SERVICE = RAGService(
                llm=llm_for_chat(), retriever=build_retriever(), reranker=build_reranker(), context_key=context_key
            )
        return _RAG_SERVICE


_INGESTION_JOB_MANAGER_LOCK = threading.Lock()
_INGESTION_JOB_MANAGER: "TickerIngestionJobManager | None" = None


def get_ticker_ingestion_job_manager() -> TickerIngestionJobManager:
    """
    Lazily construct the ticker ingestion job manager.
    """

    global _INGESTION_JOB_MANAGER
    if _INGESTION_JOB_MANAGER is not None:
        return _INGESTION_JOB_MANAGER
    with _INGESTION_JOB_MANAGER_LOCK:
        if _INGESTION_JOB_MANAGER is None:
            configured_root = (os.getenv("FINRAG_INGEST_JOBS_ROOT") or "").strip()
            jobs_root = None
            if configured_root:
                root_path = Path(os.path.expanduser(configured_root))
                jobs_root = (root_path if root_path.is_absolute() else (project_root / root_path)).resolve()
            _INGESTION_JOB_MANAGER = TickerIngestionJobManager(project_root=project_root, jobs_root=jobs_root)
        return _INGESTION_JOB_MANAGER


def start_ticker_ingestion_job(*, tickers: list[str], per_company: int) -> TickerIngestJobStatus:
    """
    Validate request payload and enqueue ticker ingestion background job.
    """

    normalized_tickers: list[str] = []
    seen: set[str] = set()
    for ticker in tickers:
        normalized = normalize_ticker(ticker)
        if normalized in seen:
            continue
        seen.add(normalized)
        normalized_tickers.append(normalized)
    if not normalized_tickers:
        raise ValueError("At least one ticker is required.")
    if per_company <= 0:
        raise ValueError("per_company must be > 0")

    cfg = build_ticker_ingestion_config(project_root=project_root)
    payload = get_ticker_ingestion_job_manager().start_job(
        tickers=normalized_tickers, per_company=per_company, config=cfg
    )
    return TickerIngestJobStatus.model_validate(payload)


def get_ticker_ingestion_job_status(job_id: str) -> TickerIngestJobStatus | None:
    """
    Fetch a ticker ingestion background job snapshot.
    """

    payload = get_ticker_ingestion_job_manager().get_job(job_id=job_id)
    if payload is None:
        return None
    return TickerIngestJobStatus.model_validate(payload)


_CONVERSATIONS = ConversationStore()
_QUERY_HISTORY = QueryHistoryStore(project_root=project_root)
_INGESTED_COMPANIES_SERVICE = IngestedCompaniesService(project_root=project_root)
_STREAM_CANCEL_REGISTRY = StreamCancelRegistry()


def _resolve_conversation_question(
    *, conversation_id: str | None, question: str
) -> tuple[str, str, list[ToolTraceEvent]]:
    return _CONVERSATIONS.resolve_question(conversation_id=conversation_id, question=question)


def _update_conversation_after_query(
    *, conversation_id: str | None, effective_question: str, response: QueryResponse
) -> None:
    _CONVERSATIONS.update_after_response(
        conversation_id=conversation_id, effective_question=effective_question, response=response
    )


def _resolve_conversation_for_stream(
    conversation_id: str | None, question: str
) -> tuple[str, str, list[ToolTraceEvent]]:
    """
    Adapter for stream runtime callback signature.
    """

    return _resolve_conversation_question(conversation_id=conversation_id, question=question)


def _update_conversation_for_stream(
    conversation_id: str | None, effective_question: str, response: QueryResponse
) -> None:
    """
    Adapter for stream runtime callback signature.
    """

    _update_conversation_after_query(
        conversation_id=conversation_id, effective_question=effective_question, response=response
    )


def _append_history_for_stream(
    req: QueryRequest, res: QueryResponse, timing_ms: dict[str, float] | None = None
) -> None:
    """
    Adapter for stream runtime callback signature.
    """

    _QUERY_HISTORY.append(req=req, res=res, timing_ms=timing_ms)


class CancelRequest(BaseModel):
    request_id: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/generation_presets")
def generation_presets():
    return {"default_mode": default_mode(), "presets": [p.to_public_dict() for p in list_generation_presets()]}


@app.post("/ingest")
def ingest_ticker(req: TickerIngestRequest):
    """
    Start ticker-based ingestion pipeline as a background job.
    """

    try:
        status = start_ticker_ingestion_job(tickers=req.requested_tickers(), per_company=req.per_company)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return status.model_dump()


@app.get("/ingest/{job_id}")
def ingest_ticker_status(job_id: str):
    """
    Return status snapshot for a ticker ingestion background job.
    """

    status = get_ticker_ingestion_job_status(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail=f"Ingestion job not found: {job_id}")
    return status.model_dump()


@app.post("/query")
async def query_docs(req: QueryRequest):
    effective_question, conversation_id, pre_tool_trace = _resolve_conversation_question(
        conversation_id=req.conversation_id, question=req.question
    )
    req_with_conversation = QueryRequest(**(req.model_dump() | {"conversation_id": conversation_id}))
    settings = _resolve_generation(req)
    req_resolved = _request_with_resolved_settings(req_with_conversation, settings)
    result = get_rag_service().answer_question(
        question=effective_question,
        settings=settings,
        tickers=req.tickers,
        filing_date_from=req.filing_date_from,
        filing_date_to=req.filing_date_to,
        conversation_id=conversation_id,
        pre_tool_trace=pre_tool_trace,
    )
    _update_conversation_after_query(
        conversation_id=conversation_id, effective_question=effective_question, response=result
    )
    _QUERY_HISTORY.append(req=req_resolved, res=result)
    return result


@app.post("/cancel")
def cancel(req: CancelRequest):
    ok = _STREAM_CANCEL_REGISTRY.cancel(request_id=(req.request_id or "").strip())
    return {"status": "ok" if ok else "not_found"}


@app.post("/query_stream")
async def query_docs_stream(req: QueryStreamRequest, request: Request):
    rag_service = get_rag_service()
    request_id, cancel_evt = _STREAM_CANCEL_REGISTRY.register(request_id=req.request_id)

    async def gen():
        try:
            async for payload in run_query_stream(
                req=req,
                request=request,
                rag_service=rag_service,
                request_id=request_id,
                cancel_evt=cancel_evt,
                resolve_conversation_question=_resolve_conversation_for_stream,
                update_conversation_after_query=_update_conversation_for_stream,
                append_history=_append_history_for_stream,
                resolve_generation=_resolve_generation,
                request_with_resolved_settings=_request_with_resolved_settings,
            ):
                yield payload
        finally:
            _STREAM_CANCEL_REGISTRY.cleanup(request_id=request_id)

    return StreamingResponse(gen(), media_type="application/x-ndjson")


@app.get("/source")
def get_source(path: str = Query(..., description="Local file path or URL")):
    return source_response(path=path, project_root=project_root)


@app.get("/source_text")
def get_source_text(path: str = Query(..., description="Local markdown/text file path")):
    p = resolve_local_source(path=path, project_root=project_root)
    suffix = p.suffix.lower()
    if suffix not in {".md", ".markdown", ".txt"}:
        raise HTTPException(status_code=415, detail="Only .md/.markdown/.txt are supported for inline text viewing")

    max_bytes_raw = os.getenv("SOURCE_TEXT_MAX_BYTES", "5000000").strip()
    try:
        max_bytes = int(max_bytes_raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="SOURCE_TEXT_MAX_BYTES must be an integer") from exc

    return {"path": str(p), "text": read_text_file(path=p, max_bytes=max_bytes)}


@app.get("/ingested_companies")
def ingested_companies():
    """
    Return the set of tickers (and best-effort company names) available in the currently ingested dataset.

    Resolution order:
    1. FINRAG_DOC_INDEX_PATH when explicitly configured.
    2. Active ingest profile chunk output directory (`doc_index.jsonl`), with latest-path fallback.
    """

    return _INGESTED_COMPANIES_SERVICE.list_companies()


@app.get("/history")
def history(limit: int = 50, summary: bool = False):
    return {"items": _QUERY_HISTORY.read(limit=limit, summary=summary), "path": str(_QUERY_HISTORY.path())}


@app.get("/history_entry")
def history_entry(id: str = Query(..., description="History entry id")):
    entry_id = (id or "").strip()
    if not entry_id:
        raise HTTPException(status_code=400, detail="Missing `id`")
    try:
        entry = _QUERY_HISTORY.read_entry(entry_id=entry_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if entry is None:
        raise HTTPException(status_code=404, detail="History entry not found")
    return entry


@app.delete("/history")
def clear_history():
    path = _QUERY_HISTORY.clear()
    return {"status": "ok", "path": str(path)}


# -------------------------------------------------------------------
# TypeScript frontend (HTML is just a very thin wrapper)
# -------------------------------------------------------------------

HTML_PATH = Path(__file__).parent / "static" / "index.html"


@app.get("/", response_class=HTMLResponse)
def index():
    # Read on request so frontend edits don't require a server restart.
    return HTML_PATH.read_text(encoding="utf-8")
