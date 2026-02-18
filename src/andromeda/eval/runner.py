from __future__ import annotations

import concurrent.futures
import json
import multiprocessing
import os
import re
import signal
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, cast

from loguru import logger
from tqdm import tqdm

from andromeda.dataclasses import TopChunk
from andromeda.eval.schema import EvalGeneration, EvalKind, EvalQuery, RetrievedChunk
from andromeda.llm.generation_controls import (
    AnswerStyle,
    AnsweringEffort,
    GenerationSettings,
    resolve_generation_settings,
)

if TYPE_CHECKING:
    from andromeda.main import RAGService
else:
    RAGService = Any


@dataclass(frozen=True)
class RunConfig:
    mode: str = "normal"

    # Optional overrides (fall back to preset when None).
    top_k_retrieve: int | None = None
    top_k_rerank: int | None = None
    draft_max_tokens: int | None = None
    final_max_tokens: int | None = None
    brief_max_tokens: int | None = None
    enable_rerank: bool | None = None
    enable_refine: bool | None = None
    answer_style: AnswerStyle | None = None
    answering_effort: AnsweringEffort | None = None
    draft_temperature: float | None = None

    # Parallelism. (Latency does not matter for offline eval runs.)
    concurrency: int = 12
    parallel_backend: str = "thread"

    # Output controls.
    max_chunks: int = 50
    query_timeout_s: float | None = 350.0
    query_max_retries: int = 1

    def resolved_settings(self) -> GenerationSettings:
        return resolve_generation_settings(
            mode=self.mode,
            top_k_retrieve=self.top_k_retrieve,
            top_k_rerank=self.top_k_rerank,
            draft_max_tokens=self.draft_max_tokens,
            final_max_tokens=self.final_max_tokens,
            brief_max_tokens=self.brief_max_tokens,
            enable_rerank=self.enable_rerank,
            enable_refine=self.enable_refine,
            answer_style=self.answer_style,
            answering_effort=self.answering_effort,
            draft_temperature=self.draft_temperature,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


WORKER_SERVICE: Any | None = None
WORKER_SETTINGS: GenerationSettings | None = None
WORKER_CFG: RunConfig | None = None


@contextmanager
def _query_timeout_guard(timeout_s: float | None):
    """
    Guard one eval query with a wall-clock timeout when supported.
    """

    if timeout_s is None or timeout_s <= 0:
        yield
        return

    if threading.current_thread() is not threading.main_thread():
        # Signal-based timers are only supported in the main thread.
        yield
        return

    if not hasattr(signal, "setitimer") or not hasattr(signal, "SIGALRM"):
        yield
        return

    def _handler(_signum: int, _frame: Any) -> None:
        raise TimeoutError(f"Timed out after {timeout_s:.1f}s")

    previous_handler = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, _handler)
    signal.setitimer(signal.ITIMER_REAL, timeout_s)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0.0)
        signal.signal(signal.SIGALRM, previous_handler)


def _is_retryable_generation_error(exc: Exception) -> bool:
    """
    Return whether an eval generation failure should be retried.
    """

    if isinstance(exc, TimeoutError):
        return True
    msg = str(exc).strip().lower()
    if not msg:
        return False
    markers = (
        "timed out",
        "timeout",
        "rate limit",
        "429",
        "500",
        "502",
        "503",
        "504",
        "connection",
        "temporarily unavailable",
        "bad gateway",
        "gateway timeout",
    )
    return any(token in msg for token in markers)


def _call_with_timeout_threadsafe(fn: Callable[[], Any], *, timeout_s: float) -> Any:
    """
    Run one callable with wall-clock timeout using a daemon thread.

    This avoids process shutdown hangs from non-daemon timeout workers.
    """

    payload: dict[str, Any] = {}
    done = threading.Event()

    def _target() -> None:
        try:
            payload["result"] = fn()
        except Exception as exc:  # noqa: BLE001
            payload["error"] = exc
        finally:
            done.set()

    worker = threading.Thread(target=_target, daemon=True, name="eval-timeout-worker")
    worker.start()

    if not done.wait(timeout_s):
        raise TimeoutError(f"Timed out after {timeout_s:.1f}s")

    if "error" in payload:
        raise cast(Exception, payload["error"])
    return payload.get("result")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def truncate(text: str | None, limit: int) -> str | None:
    if text is None:
        return None
    rendered = str(text)
    if limit <= 0 or len(rendered) <= limit:
        return rendered
    return rendered[: max(0, limit - 1)].rstrip() + "…"


def to_retrieved_chunk(chunk: TopChunk, cfg: RunConfig) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk.chunk_id,
        doc_id=chunk.doc_id,
        page_no=chunk.page_no,
        headings=list(chunk.headings or []),
        score=float(chunk.score),
        source=chunk.source,
        preview=truncate(chunk.preview, 400),
        text=chunk.text,
        context=chunk.context,
        metadata=chunk.metadata,
    )


def run_one(
    service: RAGService, query_id: str, kind: EvalKind, question: str, settings: GenerationSettings, cfg: RunConfig
) -> tuple[EvalGeneration, float, bool]:
    t0 = time.perf_counter()
    created = utcnow()
    try:
        max_attempts = max(1, int(cfg.query_max_retries) + 1)
        attempts_used = 0
        resp = None
        for attempt_idx in range(max_attempts):
            attempts_used = attempt_idx + 1
            try:
                timeout_s = cfg.query_timeout_s
                if timeout_s is None or timeout_s <= 0:
                    resp = service.answer_question(question, settings, include_retrieved_chunks=True)
                elif threading.current_thread() is threading.main_thread():
                    with _query_timeout_guard(timeout_s):
                        resp = service.answer_question(question, settings, include_retrieved_chunks=True)
                else:
                    # Thread workers cannot use signal timers.
                    resp = _call_with_timeout_threadsafe(
                        lambda: service.answer_question(question, settings, include_retrieved_chunks=True),
                        timeout_s=timeout_s,
                    )
                break
            except Exception as exc:  # noqa: BLE001
                can_retry = attempt_idx < (max_attempts - 1) and _is_retryable_generation_error(exc)
                if not can_retry:
                    raise
                backoff_s = min(2.0, 0.5 * (2**attempt_idx))
                logger.warning(
                    "Retrying eval generation for query_id={} after attempt {}/{} failed: {}",
                    query_id,
                    attempts_used,
                    max_attempts,
                    exc,
                )
                time.sleep(backoff_s)
                continue

        if resp is None:
            raise RuntimeError("Internal error: generation response is None after retries")

        chunks = [to_retrieved_chunk(tc, cfg) for tc in (resp.top_chunks or [])[: cfg.max_chunks]]
        retrieved_chunks = [to_retrieved_chunk(tc, cfg) for tc in (resp.retrieved_chunks or [])[: cfg.max_chunks]]
        generation = EvalGeneration(
            query_id=query_id,
            kind=kind,
            question=question,
            created_at=created,
            settings={
                "mode": settings.mode,
                "top_k_retrieve": settings.top_k_retrieve,
                "top_k_rerank": settings.top_k_rerank,
                "draft_max_tokens": settings.draft_max_tokens,
                "final_max_tokens": settings.final_max_tokens,
                "enable_rerank": settings.enable_rerank,
                "enable_refine": settings.enable_refine,
                "answer_style": settings.answer_style,
                "draft_temperature": settings.draft_temperature,
                "concurrency": max(1, int(cfg.concurrency)),
                "query_attempts": attempts_used,
            },
            draft_answer=resp.draft_answer,
            final_answer=resp.final_answer,
            tool_trace=[event.model_dump(mode="json") for event in (resp.tool_trace or [])],
            tool_results=[result.model_dump(mode="json") for result in (resp.tool_results or [])],
            top_chunks=chunks,
            retrieved_chunks=retrieved_chunks,
        )
        ok = True
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Error during eval generation for query_id={query_id}: {exc}", exc_info=True)
        generation = EvalGeneration(
            query_id=query_id,
            kind=kind,
            question=question,
            created_at=created,
            settings={"mode": settings.mode, "concurrency": max(1, int(cfg.concurrency))},
            error=str(exc),
        )
        ok = False

    total_ms = (time.perf_counter() - t0) * 1000.0
    generation.timing_ms["total_ms"] = total_ms
    return generation, total_ms, ok


def get_worker_index() -> int:
    identity = multiprocessing.current_process()._identity
    if identity:
        return identity[0]
    match = re.search(r"(\d+)$", multiprocessing.current_process().name)
    if match:
        return int(match.group(1))
    return 1


def worker_init(cfg_dict: dict[str, Any], gpu_ids: list[str] | None = None) -> None:
    global WORKER_SERVICE, WORKER_SETTINGS, WORKER_CFG

    if gpu_ids:
        worker_index = get_worker_index()
        gpu_id = gpu_ids[(worker_index - 1) % len(gpu_ids)]
        logger.info(f"Worker {worker_index} assigned GPU {gpu_id} (from {gpu_ids})")

        os.environ["CUDA_DEVICE_ORDER"] = os.environ.get("CUDA_DEVICE_ORDER", "PCI_BUS_ID")
        os.environ["CUDA_VISIBLE_DEVICES"] = str(gpu_id)
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.set_device(0)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Unable to pin CUDA device for worker {worker_index}: {exc}")

    cfg = RunConfig(**cfg_dict)
    settings = cfg.resolved_settings()

    import andromeda.main as main

    WORKER_SERVICE = main.get_rag_service()
    WORKER_SETTINGS = settings
    WORKER_CFG = cfg


def worker_run_one(query_id: str, kind: EvalKind, question: str) -> tuple[str, float, bool]:
    if WORKER_SERVICE is None or WORKER_SETTINGS is None or WORKER_CFG is None:
        raise RuntimeError("Worker not initialized")
    generation, total_ms, ok = run_one(WORKER_SERVICE, query_id, kind, question, WORKER_SETTINGS, WORKER_CFG)
    return generation.model_dump_json(), total_ms, ok


def run_generation(
    queries: Iterable[EvalQuery], *, out_jsonl: str | Path, cfg: RunConfig, gpu_ids: list[str] | None = None
) -> dict[str, Any]:
    """
    Run eval queries through `RAGService.answer_question()` and write JSONL outputs.
    """

    output_path = Path(out_jsonl)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    query_specs: list[tuple[str, EvalKind, str]] = [
        (query.id, cast(EvalKind, query.kind), query.question) for query in queries
    ]
    if not query_specs:
        with output_path.open("w", encoding="utf-8"):
            pass
        return {"n": 0, "n_ok": 0, "n_err": 0, "avg_total_ms": 0.0, "wall_total_ms": 0.0, "settings": cfg.to_dict()}

    n = 0
    n_ok = 0
    n_err = 0
    total_ms = 0.0
    wall_t0 = time.perf_counter()

    concurrency = max(1, int(cfg.concurrency))
    parallel_backend = (cfg.parallel_backend or "process").strip().lower()
    if parallel_backend not in {"process", "thread"}:
        logger.warning(f"Unknown parallel_backend='{cfg.parallel_backend}', falling back to 'process'.")
        parallel_backend = "process"

    if gpu_ids is None:
        raw_gpu_ids = (os.getenv("FINRAG_EVAL_GPU_IDS") or "").strip()
        if raw_gpu_ids:
            gpu_ids = [item.strip() for item in raw_gpu_ids.split(",") if item.strip()]

    if concurrency <= 1 or len(query_specs) <= 1:
        import andromeda.main as main

        service = main.get_rag_service()
        settings = cfg.resolved_settings()
        with output_path.open("w", encoding="utf-8") as out_file:
            for query_id, kind, question in tqdm(query_specs, desc="Inferencing on eval queries"):
                generation, item_ms, ok = run_one(service, query_id, kind, question, settings, cfg)
                n += 1
                total_ms += item_ms
                if ok:
                    n_ok += 1
                else:
                    n_err += 1
                out_file.write(generation.model_dump_json())
                out_file.write("\n")
    elif parallel_backend == "thread":
        import andromeda.main as main

        service = main.get_rag_service()
        settings = cfg.resolved_settings()
        effective_workers = min(concurrency, len(query_specs))
        with output_path.open("w", encoding="utf-8") as out_file:
            pending: dict[int, str] = {}
            next_to_write = 0

            with concurrent.futures.ThreadPoolExecutor(max_workers=effective_workers) as executor:
                future_to_index = {
                    executor.submit(run_one, service, query_id, kind, question, settings, cfg): idx
                    for idx, (query_id, kind, question) in enumerate(query_specs)
                }

                for future in tqdm(
                    concurrent.futures.as_completed(future_to_index),
                    total=len(future_to_index),
                    desc=f"Inferencing on eval queries with {concurrency} thread workers",
                ):
                    idx = future_to_index[future]
                    query_id, kind, question = query_specs[idx]
                    try:
                        generation, item_ms, ok = future.result()
                        line = generation.model_dump_json()
                    except Exception as exc:  # noqa: BLE001
                        generation = EvalGeneration(
                            query_id=query_id,
                            kind=kind,
                            question=question,
                            created_at=utcnow(),
                            settings={"mode": cfg.mode, "concurrency": concurrency, "parallel_backend": "thread"},
                            error=f"Thread worker failed: {exc}",
                        )
                        generation.timing_ms["total_ms"] = 0.0
                        line, item_ms, ok = generation.model_dump_json(), 0.0, False

                    n += 1
                    total_ms += item_ms
                    if ok:
                        n_ok += 1
                    else:
                        n_err += 1

                    pending[idx] = line
                    while next_to_write in pending:
                        out_file.write(pending.pop(next_to_write))
                        out_file.write("\n")
                        next_to_write += 1

            if pending:
                for idx in sorted(pending):
                    out_file.write(pending[idx])
                    out_file.write("\n")
    else:
        with output_path.open("w", encoding="utf-8") as out_file:
            pending: dict[int, str] = {}
            next_to_write = 0

            mp_context = multiprocessing.get_context("spawn")
            effective_workers = min(concurrency, len(query_specs))
            with concurrent.futures.ProcessPoolExecutor(
                max_workers=effective_workers,
                mp_context=mp_context,
                initializer=worker_init,
                initargs=(cfg.to_dict(), gpu_ids),
            ) as executor:
                future_to_index = {
                    executor.submit(worker_run_one, query_id, kind, question): idx
                    for idx, (query_id, kind, question) in enumerate(query_specs)
                }

                for future in tqdm(
                    concurrent.futures.as_completed(future_to_index),
                    total=len(future_to_index),
                    desc=f"Inferencing on eval queries with {concurrency} workers",
                ):
                    idx = future_to_index[future]
                    query_id, kind, question = query_specs[idx]
                    try:
                        line, item_ms, ok = future.result()
                    except Exception as exc:  # noqa: BLE001
                        generation = EvalGeneration(
                            query_id=query_id,
                            kind=kind,
                            question=question,
                            created_at=utcnow(),
                            settings={"mode": cfg.mode, "concurrency": concurrency},
                            error=f"Worker failed: {exc}",
                        )
                        generation.timing_ms["total_ms"] = 0.0
                        line, item_ms, ok = generation.model_dump_json(), 0.0, False

                    n += 1
                    total_ms += item_ms
                    if ok:
                        n_ok += 1
                    else:
                        n_err += 1

                    pending[idx] = line
                    while next_to_write in pending:
                        out_file.write(pending.pop(next_to_write))
                        out_file.write("\n")
                        next_to_write += 1

            if pending:
                for idx in sorted(pending):
                    out_file.write(pending[idx])
                    out_file.write("\n")

    wall_total_ms = (time.perf_counter() - wall_t0) * 1000.0
    return {
        "n": n,
        "n_ok": n_ok,
        "n_err": n_err,
        "avg_total_ms": (total_ms / n) if n else 0.0,
        "wall_total_ms": wall_total_ms,
        "settings": cfg.to_dict(),
    }


def save_json(data: dict[str, Any], path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
