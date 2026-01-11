from __future__ import annotations

import csv
import json
import os
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:  # pragma: no cover
    import fcntl  # type: ignore
except Exception:  # noqa: BLE001 - optional on non-POSIX
    fcntl = None  # type: ignore


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    raw = raw.strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def traces_enabled() -> bool:
    return _env_bool("FINRAG_TRACES_ENABLED", default=True)


def traces_root() -> Path:
    raw = (os.getenv("FINRAG_TRACES_DIR") or "").strip()
    root = Path(os.path.expanduser(raw)).resolve() if raw else (PROJECT_ROOT / "logs" / "traces").resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def trace_run_dir(*, now: datetime | None = None) -> Path:
    now = now or datetime.now(timezone.utc)
    day = now.strftime("%Y%m%d")
    run_dir = (traces_root() / f"trace_run.{day}").resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


@contextmanager
def run_dir_lock(run_dir: Path):
    """
    Cross-process lock for appending/updating artifacts within a run dir.

    This avoids races between trace writers and the review UI updating review.csv.
    """

    lock_path = (run_dir / ".lock").resolve()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if fcntl is None:  # pragma: no cover
        yield
        return
    with lock_path.open("a", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


TRACE_REVIEW_FIELDNAMES = [
    "query_id",
    "kind",
    "question",
    "tags",
    "target_tickers",
    "human_label",
    "human_notes",
]


def _ensure_review_csv(run_dir: Path) -> Path:
    path = (run_dir / "review.csv").resolve()
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(TRACE_REVIEW_FIELDNAMES))
            w.writeheader()
    except FileExistsError:
        pass
    return path


def _sanitize_csv_cell(value: object) -> str:
    s = str(value or "")
    # Keep rows single-line for grep/tail ergonomics (review UI doesn't need newlines).
    s = " ".join(s.splitlines()).strip()
    return s


@dataclass(frozen=True)
class TraceWriteResult:
    run_dir: Path
    generations_path: Path
    review_path: Path


def write_trace(*, generation: dict[str, Any], review_row: dict[str, Any], now: datetime | None = None) -> TraceWriteResult:
    """
    Append a single trace to:
      - generations.jsonl (full payload)
      - review.csv (lightweight index for the review UI)
    """

    run_dir = trace_run_dir(now=now)
    generations_path = (run_dir / "generations.jsonl").resolve()
    review_path = _ensure_review_csv(run_dir)

    with run_dir_lock(run_dir):
        run_dir.mkdir(parents=True, exist_ok=True)

        generations_path.parent.mkdir(parents=True, exist_ok=True)
        with generations_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(generation, ensure_ascii=False) + "\n")

        row = {k: "" for k in TRACE_REVIEW_FIELDNAMES}
        for k, v in (review_row or {}).items():
            if k in row:
                row[k] = _sanitize_csv_cell(v)
        with review_path.open("a", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(TRACE_REVIEW_FIELDNAMES))
            w.writerow(row)

    return TraceWriteResult(run_dir=run_dir, generations_path=generations_path, review_path=review_path)


def trace_chunk_limits() -> tuple[int, int, int, int]:
    """
    Returns (max_chunks, preview_chars, text_chars, context_chars).
    """

    max_chunks = max(0, _env_int("FINRAG_TRACES_MAX_CHUNKS", 50))
    preview_chars = max(0, _env_int("FINRAG_TRACES_CHUNK_PREVIEW_CHARS", 400))
    text_chars = max(0, _env_int("FINRAG_TRACES_CHUNK_TEXT_CHARS", 2000))
    context_chars = max(0, _env_int("FINRAG_TRACES_CHUNK_CONTEXT_CHARS", 2000))
    return max_chunks, preview_chars, text_chars, context_chars
