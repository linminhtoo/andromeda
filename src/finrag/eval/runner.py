import atexit
import concurrent.futures
import json
import multiprocessing
import os
import re
import shutil
import signal
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable

from loguru import logger
from tqdm import tqdm

from finrag.dataclasses import TopChunk
from finrag.eval.schema import EvalGeneration, EvalKind, EvalQuery, RetrievedChunk
from finrag.generation_controls import AnswerStyle, GenerationSettings, resolve_generation_settings

if TYPE_CHECKING:
    # try to avoid importing main here to prevent potential issues with multiprocessing
    from finrag.main import RAGService
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
    enable_rerank: bool | None = None
    enable_refine: bool | None = None
    answer_style: AnswerStyle | None = None
    draft_temperature: float | None = None

    # Parallelism. (Latency doesn't matter for offline eval runs.)
    concurrency: int = 8

    # Output controls.
    max_chunks: int = 50
    chunk_text_chars: int = 2000
    chunk_context_chars: int = 2000

    def resolved_settings(self) -> GenerationSettings:
        return resolve_generation_settings(
            mode=self.mode,
            top_k_retrieve=self.top_k_retrieve,
            top_k_rerank=self.top_k_rerank,
            draft_max_tokens=self.draft_max_tokens,
            final_max_tokens=self.final_max_tokens,
            enable_rerank=self.enable_rerank,
            enable_refine=self.enable_refine,
            answer_style=self.answer_style,
            draft_temperature=self.draft_temperature,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_WORKER_SERVICE: Any | None = None
_WORKER_SETTINGS: GenerationSettings | None = None
_WORKER_CFG: RunConfig | None = None


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _truncate(text: str | None, limit: int) -> str | None:
    if text is None:
        return None
    s = str(text)
    if limit <= 0 or len(s) <= limit:
        return s
    return s[: max(0, limit - 1)].rstrip() + "…"


def _to_retrieved_chunk(chunk: TopChunk, cfg: RunConfig) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk.chunk_id,
        doc_id=chunk.doc_id,
        page_no=chunk.page_no,
        headings=list(chunk.headings or []),
        score=float(chunk.score),
        source=chunk.source,
        preview=_truncate(chunk.preview, 400),
        text=_truncate(chunk.text, cfg.chunk_text_chars),
        context=_truncate(chunk.context, cfg.chunk_context_chars),
        metadata=chunk.metadata,
    )


def _run_one(
    service: RAGService, query_id: str, kind: EvalKind, question: str, settings: GenerationSettings, cfg: RunConfig
) -> tuple[EvalGeneration, float, bool]:
    t0 = time.perf_counter()
    created = _utcnow()
    try:
        resp = service.answer_question(question, settings, include_retrieved_chunks=True)
        chunks = [_to_retrieved_chunk(tc, cfg) for tc in (resp.top_chunks or [])[: cfg.max_chunks]]
        retrieved_chunks = [_to_retrieved_chunk(tc, cfg) for tc in (resp.retrieved_chunks or [])[: cfg.max_chunks]]
        gen = EvalGeneration(
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
            },
            draft_answer=resp.draft_answer,
            final_answer=resp.final_answer,
            top_chunks=chunks,
            retrieved_chunks=retrieved_chunks,
        )
        ok = True
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Error during eval generation for query_id={query_id}: {exc}", exc_info=True)
        gen = EvalGeneration(
            query_id=query_id,
            kind=kind,
            question=question,
            created_at=created,
            settings={"mode": settings.mode, "concurrency": max(1, int(cfg.concurrency))},
            error=str(exc),
        )
        ok = False
    t1 = time.perf_counter()
    ms = (t1 - t0) * 1000.0
    gen.timing_ms["total_ms"] = ms
    return gen, ms, ok


def get_worker_index() -> int:
    identity = multiprocessing.current_process()._identity
    if identity:
        return identity[0]
    match = re.search(r"(\d+)$", multiprocessing.current_process().name)
    if match:
        return int(match.group(1))
    return 1


def _worker_init(
    cfg_dict: dict[str, Any], storage_path: str | None, milvus_copies_dir: str | None, gpu_ids: list[str] | None = None
) -> None:
    global _WORKER_SERVICE, _WORKER_SETTINGS, _WORKER_CFG

    if storage_path is not None:
        os.environ["QDRANT_STORAGE_PATH"] = storage_path

    if gpu_ids:
        worker_index = get_worker_index()
        gpu_id = gpu_ids[(worker_index - 1) % len(gpu_ids)]
        logger.info(f"Worker {worker_index} assigned GPU {gpu_id} (from {gpu_ids})")

        # In a spawn'ed worker, this runs before we import `finrag.main` (and
        # before sentence-transformers loads torch models), so we can safely
        # restrict visibility. This ensures code that defaults to `cuda:0`
        # actually uses the intended physical GPU.
        # NOTE that this is different from logic in process_html_to_markdown.py where setting env var was too late
        # and torch.cuda.set_device(gpu_id) was required instead.
        os.environ["CUDA_DEVICE_ORDER"] = os.environ.get("CUDA_DEVICE_ORDER", "PCI_BUS_ID")
        os.environ["CUDA_VISIBLE_DEVICES"] = str(gpu_id)
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.set_device(0)
        except Exception as exc:  # noqa: BLE001 - best effort logging
            logger.warning(f"Unable to pin CUDA device for worker {worker_index}: {exc}")

    # HOTFIX: Milvus Lite uses an exclusive lock on local DB files, so spawned
    # workers cannot share the same `MILVUS_PATH`. Duplicate the DB per worker.
    backend = os.getenv("RETRIEVER_BACKEND", "milvus").strip().lower()
    milvus_uri = (os.getenv("MILVUS_URI") or "").strip()
    if backend == "milvus" and "://" not in milvus_uri:
        original_home = (os.environ.get("HOME") or "").strip()
        milvus_path = (os.getenv("MILVUS_PATH") or "").strip()
        if not milvus_path:
            project_root = Path(__file__).resolve().parents[3]
            milvus_path = str(project_root / "data" / "milvus.db")
        base = Path(os.path.expanduser(milvus_path)).resolve()
        if base.is_dir():
            base = base / "milvus.db"
        if base.exists():
            if milvus_copies_dir:
                copies_root = Path(milvus_copies_dir)
                copies_root.mkdir(parents=True, exist_ok=True)
                worker_dir = copies_root / f"worker_{os.getpid()}"
                worker_dir.mkdir(parents=True, exist_ok=True)
            else:
                worker_dir = Path(tempfile.mkdtemp(prefix="finrag_eval_milvus_"))

            # Milvus Lite uses `~/.cache/milvus` for internal storage; when many
            # milvus-lite instances start concurrently, they can race on the same
            # shared cache dir. Isolate HOME/XDG_CACHE_HOME per worker process.
            os.environ["HOME"] = str(worker_dir)
            os.environ["XDG_CACHE_HOME"] = str(worker_dir / ".cache")
            (worker_dir / ".cache" / "milvus").mkdir(parents=True, exist_ok=True)

            # Keep HF / torch caches pointed at the user's real home so we don't
            # redownload models per worker.
            if original_home:
                os.environ.setdefault("HF_HOME", str(Path(original_home) / ".cache" / "huggingface"))
                os.environ.setdefault("TORCH_HOME", str(Path(original_home) / ".cache" / "torch"))
                os.environ.setdefault(
                    "SENTENCE_TRANSFORMERS_HOME", str(Path(original_home) / ".cache" / "sentence_transformers")
                )

            dst = worker_dir / base.name
            shutil.copy2(base, dst)
            os.environ["MILVUS_PATH"] = str(dst)
            os.environ.pop("MILVUS_URI", None)

            keep_worker_dirs = _env_bool("FINRAG_EVAL_KEEP_WORKDIRS", default=False)

            def _cleanup_milvus_lite() -> None:
                # Best-effort cleanup: milvus-lite starts a subprocess; ensure it
                # is stopped when the worker process exits. Then delete the
                # per-worker directory unless explicitly kept for debugging.
                try:
                    from milvus_lite.server_manager import server_manager_instance

                    server_manager_instance.release_all()
                except Exception:
                    pass
                if not keep_worker_dirs:
                    shutil.rmtree(worker_dir, ignore_errors=True)

            atexit.register(_cleanup_milvus_lite)

    cfg = RunConfig(**cfg_dict)
    settings = cfg.resolved_settings()

    import finrag.main as main

    _WORKER_SERVICE = main.get_rag_service()
    _WORKER_SETTINGS = settings
    _WORKER_CFG = cfg


def _worker_run_one(query_id: str, kind: EvalKind, question: str) -> tuple[str, float, bool]:
    if _WORKER_SERVICE is None or _WORKER_SETTINGS is None or _WORKER_CFG is None:
        raise RuntimeError("Worker not initialized")
    gen, ms, ok = _run_one(_WORKER_SERVICE, query_id, kind, question, _WORKER_SETTINGS, _WORKER_CFG)
    return gen.model_dump_json(), ms, ok


def run_generation(
    queries: Iterable[EvalQuery],
    *,
    out_jsonl: str | Path,
    cfg: RunConfig,
    storage_path: str | None = None,
    gpu_ids: list[str] | None = None,
) -> dict[str, Any]:
    """
    Run `EvalQuery`s through the app's `RAGService.answer_question()` pipeline and
    write `EvalGeneration` JSONL.
    """
    p = Path(out_jsonl)
    p.parent.mkdir(parents=True, exist_ok=True)
    keep_worker_dirs = _env_bool("FINRAG_EVAL_KEEP_WORKDIRS", default=False)

    # `finrag.main` lazily constructs a global RAG service via `get_rag_service()`.
    # Reuse it here to avoid initializing the whole stack twice.
    if storage_path is not None:
        os.environ["QDRANT_STORAGE_PATH"] = storage_path
    queries_list = list(queries)
    query_specs: list[tuple[str, EvalKind, str]] = [(q.id, q.kind, q.question) for q in queries_list]
    n = 0
    n_ok = 0
    n_err = 0
    total_ms = 0.0
    concurrency = max(1, int(cfg.concurrency))
    wall_t0 = time.perf_counter()

    # Allow setting GPU IDs via env without touching CLI.
    if gpu_ids is None:
        raw = (os.getenv("FINRAG_EVAL_GPU_IDS") or "").strip()
        if raw:
            gpu_ids = [s.strip() for s in raw.split(",") if s.strip()]

    if concurrency <= 1 or len(query_specs) <= 1:
        import finrag.main as main

        service = main.get_rag_service()
        settings = cfg.resolved_settings()
        with p.open("w", encoding="utf-8") as f:
            for query_id, kind, question in tqdm(query_specs, desc="Inferencing on eval queries"):
                gen, ms, ok = _run_one(service, query_id, kind, question, settings, cfg)
                n += 1
                total_ms += ms
                if ok:
                    n_ok += 1
                else:
                    n_err += 1
                f.write(gen.model_dump_json())
                f.write("\n")
    else:
        with p.open("w", encoding="utf-8") as f:
            pending: dict[int, str] = {}
            next_to_write = 0

            mp_ctx = multiprocessing.get_context("spawn")
            milvus_copies_root = p.parent / "_milvus_eval_copies"
            if not keep_worker_dirs:
                shutil.rmtree(milvus_copies_root, ignore_errors=True)
            milvus_copies_root.mkdir(parents=True, exist_ok=True)

            def _cleanup_parent() -> None:
                if keep_worker_dirs:
                    return
                shutil.rmtree(milvus_copies_root, ignore_errors=True)

            atexit.register(_cleanup_parent)

            def _signal_handler(signum, _frame) -> None:
                _cleanup_parent()
                raise SystemExit(128 + int(signum))

            for sig in (signal.SIGTERM, signal.SIGINT):
                try:
                    signal.signal(sig, _signal_handler)
                except Exception:
                    pass

            effective_workers = min(concurrency, len(query_specs))

            with concurrent.futures.ProcessPoolExecutor(
                max_workers=effective_workers,
                mp_context=mp_ctx,
                initializer=_worker_init,
                initargs=(cfg.to_dict(), storage_path, str(milvus_copies_root), gpu_ids),
            ) as ex:
                fut_to_idx = {
                    ex.submit(_worker_run_one, query_id, kind, question): i
                    for i, (query_id, kind, question) in enumerate(query_specs)
                }

                for fut in tqdm(
                    concurrent.futures.as_completed(fut_to_idx),
                    total=len(fut_to_idx),
                    desc=f"Inferencing on eval queries with {concurrency} workers",
                ):
                    i = fut_to_idx[fut]
                    query_id, kind, question = query_specs[i]
                    try:
                        line, ms, ok = fut.result()
                    except Exception as exc:  # noqa: BLE001
                        created = _utcnow()
                        gen = EvalGeneration(
                            query_id=query_id,
                            kind=kind,
                            question=question,
                            created_at=created,
                            settings={"mode": cfg.mode, "concurrency": concurrency},
                            error=f"Worker failed: {exc}",
                        )
                        gen.timing_ms["total_ms"] = 0.0
                        line, ms, ok = gen.model_dump_json(), 0.0, False

                    n += 1
                    total_ms += ms
                    if ok:
                        n_ok += 1
                    else:
                        n_err += 1

                    pending[i] = line
                    while next_to_write in pending:
                        f.write(pending.pop(next_to_write))
                        f.write("\n")
                        next_to_write += 1
                        import torch

                        torch.cuda.empty_cache()

            if pending:
                for i in sorted(pending):
                    f.write(pending[i])
                    f.write("\n")

            _cleanup_parent()

    wall_t1 = time.perf_counter()
    wall_total_ms = (wall_t1 - wall_t0) * 1000.0

    summary = {
        "n": n,
        "n_ok": n_ok,
        "n_err": n_err,
        "avg_total_ms": (total_ms / n) if n else 0.0,
        "wall_total_ms": wall_total_ms,
        "settings": cfg.to_dict(),
    }
    return summary


def save_json(data: dict[str, Any], path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
