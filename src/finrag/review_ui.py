from __future__ import annotations

import csv
import json
import mimetypes
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel

from finrag.traces import run_dir_lock


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = Path(__file__).parent / "static"
REVIEW_HTML_PATH = STATIC_DIR / "review.html"
FAVICON_PATH = STATIC_DIR / "favicon.ico"

_CACHE_LOCK = threading.Lock()
_WRITE_LOCK = threading.Lock()


def _env_paths(name: str) -> list[Path]:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return []
    parts = [p.strip() for p in raw.split(os.pathsep) if p.strip()]
    return [Path(p).expanduser().resolve() for p in parts]


def _review_roots() -> list[Path]:
    roots = _env_paths("FINRAG_REVIEW_ROOTS")
    if roots:
        base = roots
    else:
        base = [(PROJECT_ROOT / "eval" / "results").resolve()]

    # Also discover live-query traces by default (written by the main app).
    traces_root = (PROJECT_ROOT / "logs" / "traces").resolve()
    if traces_root not in base:
        base.append(traces_root)
    return base


def _is_allowed_path(path: Path) -> bool:
    roots = _review_roots()
    return any(path == root or path.is_relative_to(root) for root in roots)


def _discover_run_dirs() -> list[Path]:
    runs: set[Path] = set()
    for root in _review_roots():
        if not root.exists():
            continue
        for pat in ("eval_run.*", "*/eval_run.*", "trace_run.*", "*/trace_run.*"):
            for p in root.glob(pat):
                if p.is_dir():
                    runs.add(p.resolve())

    def _latest_mtime_ns(p: Path) -> int:
        try:
            mt = p.stat().st_mtime_ns
        except Exception:  # noqa: BLE001
            return 0
        for name in ("review.csv", "generations.jsonl", "cases.jsonl"):
            try:
                mt = max(mt, (p / name).stat().st_mtime_ns)
            except FileNotFoundError:
                continue
            except Exception:  # noqa: BLE001
                continue
        return mt

    return sorted(runs, key=_latest_mtime_ns, reverse=True)


def _resolve_run_dir(run_dir: str | None) -> Path:
    run_dir = (run_dir or "").strip()
    if not run_dir:
        runs = _discover_run_dirs()
        if not runs:
            raise HTTPException(
                status_code=404, detail=f"No eval runs found under: {', '.join(str(r) for r in _review_roots())}"
            )
        preferred = [p for p in runs if (p / "review.csv").exists() and (p / "generations.jsonl").exists()]
        return preferred[0] if preferred else runs[0]

    p = Path(os.path.expanduser(run_dir))
    if not p.is_absolute():
        p = (PROJECT_ROOT / p).resolve()
    else:
        p = p.resolve()

    if not p.exists() or not p.is_dir():
        raise HTTPException(status_code=404, detail=f"Run dir not found: {p}")
    if not _is_allowed_path(p):
        raise HTTPException(
            status_code=403,
            detail=("Run dir is outside FINRAG_REVIEW_ROOTS. Set FINRAG_REVIEW_ROOTS to a colon-separated allowlist."),
        )
    return p


def _read_review_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Missing review.csv: {path} (run `python3 scripts/score_eval.py --run-dir <run_dir>` first)",
        )
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            r = csv.DictReader(f)
            fieldnames = list(r.fieldnames or [])
            rows: list[dict[str, str]] = []
            for row in r:
                rows.append({k: (v if v is not None else "") for k, v in row.items()})
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to read review.csv: {exc}") from exc

    return fieldnames, rows


def _read_generations_jsonl(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Missing generations.jsonl: {path}")
    out: dict[str, dict[str, Any]] = {}
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                if not isinstance(obj, dict):
                    continue
                qid = str(obj.get("query_id") or "").strip()
                if not qid:
                    continue
                out[qid] = obj
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to read generations.jsonl: {exc}") from exc
    return out


@dataclass(frozen=True)
class _RunCache:
    run_dir: Path
    review_path: Path
    generations_path: Path
    review_mtime_ns: int
    generations_mtime_ns: int
    review_fieldnames: list[str]
    review_rows: list[dict[str, str]]
    review_by_id: dict[str, dict[str, str]]
    generations_by_id: dict[str, dict[str, Any]]


_RUN_CACHE: dict[str, _RunCache] = {}


def _load_run_cache(run_dir: Path) -> _RunCache:
    review_path = run_dir / "review.csv"
    generations_path = run_dir / "generations.jsonl"
    if not review_path.exists():
        # Keep this error message aligned with the README workflow.
        raise HTTPException(
            status_code=404, detail=f"Missing review.csv in run dir: {review_path} (run scripts/score_eval.py first)"
        )
    if not generations_path.exists():
        raise HTTPException(status_code=404, detail=f"Missing generations.jsonl in run dir: {generations_path}")

    review_mtime_ns = review_path.stat().st_mtime_ns
    generations_mtime_ns = generations_path.stat().st_mtime_ns

    key = str(run_dir)
    with _CACHE_LOCK:
        cached = _RUN_CACHE.get(key)
        if (
            cached is not None
            and cached.review_mtime_ns == review_mtime_ns
            and cached.generations_mtime_ns == generations_mtime_ns
        ):
            return cached

    with run_dir_lock(run_dir):
        fieldnames, rows = _read_review_csv(review_path)
        generations_by_id = _read_generations_jsonl(generations_path)

    review_by_id: dict[str, dict[str, str]] = {}
    for row in rows:
        qid = (row.get("query_id") or row.get("id") or "").strip()
        if qid:
            review_by_id[qid] = row

    loaded = _RunCache(
        run_dir=run_dir,
        review_path=review_path,
        generations_path=generations_path,
        review_mtime_ns=review_mtime_ns,
        generations_mtime_ns=generations_mtime_ns,
        review_fieldnames=fieldnames,
        review_rows=rows,
        review_by_id=review_by_id,
        generations_by_id=generations_by_id,
    )
    with _CACHE_LOCK:
        _RUN_CACHE[key] = loaded
    return loaded


def _normalize_label(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        raise HTTPException(status_code=400, detail="human_label must be 0/1 (or empty)")
    if isinstance(value, int):
        if value in (0, 1):
            return str(value)
        raise HTTPException(status_code=400, detail="human_label must be 0/1 (or empty)")
    if isinstance(value, str):
        v = value.strip()
        if v == "":
            return ""
        if v in ("0", "1"):
            return v
        raise HTTPException(status_code=400, detail="human_label must be 0/1 (or empty)")
    raise HTTPException(status_code=400, detail="human_label must be 0/1 (or empty)")


def _write_review_csv(
    path: Path, *, fieldnames: list[str], rows: list[dict[str, str]], query_id: str, human_label: str, human_notes: str
) -> None:
    updated = False
    out_rows: list[dict[str, str]] = []
    for row in rows:
        qid = (row.get("query_id") or row.get("id") or "").strip()
        if qid == query_id:
            row = dict(row)
            row["human_label"] = human_label
            row["human_notes"] = human_notes
            updated = True
        out_rows.append(row)

    if not updated:
        raise HTTPException(status_code=404, detail=f"query_id not found in review.csv: {query_id}")

    tmp = path.with_name(path.name + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            for row in out_rows:
                w.writerow({k: row.get(k, "") for k in fieldnames})
        tmp.replace(path)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to write review.csv: {exc}") from exc


class ReviewRunInfo(BaseModel):
    run_dir: str
    name: str
    has_review_csv: bool
    has_generations_jsonl: bool
    has_cases_jsonl: bool


class ReviewRunsResponse(BaseModel):
    runs: list[ReviewRunInfo]


class ReviewCaseListItem(BaseModel):
    query_id: str
    kind: str
    question: str
    tags: str = ""
    target_tickers: str = ""
    human_label: str = ""
    judge_prediction: str = ""
    has_error: bool = False
    n_reranked_chunks: int = 0
    n_retrieved_chunks: int = 0


class ReviewCasesResponse(BaseModel):
    run_dir: str
    n_cases: int
    n_labeled: int
    n_unlabeled: int
    n_pass: int
    n_fail: int
    cases: list[ReviewCaseListItem]


class ReviewCaseResponse(BaseModel):
    run_dir: str
    query_id: str
    review_row: dict[str, str]
    generation: dict[str, Any] | None


class ReviewUpdateRequest(BaseModel):
    run_dir: str
    query_id: str
    human_label: int | str | None = None
    human_notes: str | None = None


class ReviewUpdateResponse(BaseModel):
    status: str
    run_dir: str
    query_id: str


router = APIRouter()


@router.get("/favicon.ico")
def review_favicon():
    if not FAVICON_PATH.exists():
        raise HTTPException(status_code=404, detail="favicon.ico not found")
    return FileResponse(path=FAVICON_PATH, media_type="image/x-icon")


@router.get("/review", response_class=HTMLResponse)
def review_page():
    if not REVIEW_HTML_PATH.exists():
        raise HTTPException(status_code=500, detail=f"Missing review UI HTML: {REVIEW_HTML_PATH}")
    # Read on request so frontend edits don't require a server restart.
    return REVIEW_HTML_PATH.read_text(encoding="utf-8")


def _source_roots() -> list[Path]:
    raw = os.getenv("SOURCE_ROOTS")
    if raw:
        parts = [p.strip() for p in raw.split(os.pathsep) if p.strip()]
        return [Path(p).expanduser().resolve() for p in parts]
    return [PROJECT_ROOT, (PROJECT_ROOT / "data").resolve()]


def _resolve_local_source(path: str) -> Path:
    path = (path or "").strip()
    if not path:
        raise HTTPException(status_code=400, detail="Missing `path`")

    p = Path(os.path.expanduser(path))
    if not p.is_absolute():
        p = (PROJECT_ROOT / p).resolve()
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


@router.get("/source")
def get_source(path: str = Query(..., description="Local file path or URL")):
    path = (path or "").strip()
    if path.startswith(("http://", "https://")):
        return RedirectResponse(url=path)
    p = _resolve_local_source(path)
    media_type, _enc = mimetypes.guess_type(str(p))
    return FileResponse(
        path=p, media_type=media_type or "application/octet-stream", filename=p.name, content_disposition_type="inline"
    )


@router.get("/source_text")
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


@router.get("/api/review/runs", response_model=ReviewRunsResponse)
def review_runs():
    runs: list[ReviewRunInfo] = []
    for run_dir in _discover_run_dirs():
        runs.append(
            ReviewRunInfo(
                run_dir=str(run_dir),
                name=run_dir.name,
                has_review_csv=(run_dir / "review.csv").exists(),
                has_generations_jsonl=(run_dir / "generations.jsonl").exists(),
                has_cases_jsonl=(run_dir / "cases.jsonl").exists(),
            )
        )
    return ReviewRunsResponse(runs=runs)


@router.get("/api/review/cases", response_model=ReviewCasesResponse)
def review_cases(run_dir: str | None = Query(default=None)):
    rd = _resolve_run_dir(run_dir)
    cache = _load_run_cache(rd)

    cases: list[ReviewCaseListItem] = []
    n_pass = 0
    n_fail = 0
    n_unlabeled = 0

    for row in cache.review_rows:
        qid = (row.get("query_id") or row.get("id") or "").strip()
        if not qid:
            continue
        gen = cache.generations_by_id.get(qid)
        label = (row.get("human_label") or "").strip()
        if label == "0":
            n_pass += 1
        elif label == "1":
            n_fail += 1
        else:
            n_unlabeled += 1

        top_chunks = gen.get("top_chunks") if isinstance(gen, dict) else None
        retrieved_chunks = gen.get("retrieved_chunks") if isinstance(gen, dict) else None
        n_reranked = len(top_chunks) if isinstance(top_chunks, list) else 0
        n_retrieved = len(retrieved_chunks) if isinstance(retrieved_chunks, list) else 0

        cases.append(
            ReviewCaseListItem(
                query_id=qid,
                kind=(row.get("kind") or "").strip(),
                question=(row.get("question") or "").strip(),
                tags=(row.get("tags") or "").strip(),
                target_tickers=(row.get("target_tickers") or "").strip(),
                human_label=label,
                judge_prediction=(row.get("judge_prediction") or "").strip(),
                has_error=bool(gen and isinstance(gen, dict) and (gen.get("error") or "").strip()),
                n_reranked_chunks=n_reranked,
                n_retrieved_chunks=n_retrieved,
            )
        )

    n_labeled = n_pass + n_fail
    return ReviewCasesResponse(
        run_dir=str(cache.run_dir),
        n_cases=len(cases),
        n_labeled=n_labeled,
        n_unlabeled=n_unlabeled,
        n_pass=n_pass,
        n_fail=n_fail,
        cases=cases,
    )


@router.get("/api/review/case", response_model=ReviewCaseResponse)
def review_case(run_dir: str | None = Query(default=None), query_id: str = Query(...)):
    rd = _resolve_run_dir(run_dir)
    cache = _load_run_cache(rd)

    qid = (query_id or "").strip()
    if not qid:
        raise HTTPException(status_code=400, detail="Missing query_id")

    row = cache.review_by_id.get(qid)
    if row is None:
        raise HTTPException(status_code=404, detail=f"query_id not found in review.csv: {qid}")

    gen = cache.generations_by_id.get(qid)
    return ReviewCaseResponse(run_dir=str(cache.run_dir), query_id=qid, review_row=row, generation=gen)


@router.post("/api/review/update", response_model=ReviewUpdateResponse)
def review_update(req: ReviewUpdateRequest):
    rd = _resolve_run_dir(req.run_dir)
    cache = _load_run_cache(rd)

    qid = (req.query_id or "").strip()
    if not qid:
        raise HTTPException(status_code=400, detail="Missing query_id")

    label = _normalize_label(req.human_label)
    notes = req.human_notes or ""

    with run_dir_lock(rd), _WRITE_LOCK:
        fieldnames, rows = _read_review_csv(cache.review_path)
        if "human_label" not in fieldnames:
            fieldnames.append("human_label")
        if "human_notes" not in fieldnames:
            fieldnames.append("human_notes")
        _write_review_csv(
            cache.review_path, fieldnames=fieldnames, rows=rows, query_id=qid, human_label=label, human_notes=notes
        )

    with _CACHE_LOCK:
        _RUN_CACHE.pop(str(rd), None)

    return ReviewUpdateResponse(status="ok", run_dir=str(rd), query_id=qid)


def _export_label_filter(label: str | None) -> str | None:
    """
    Returns:
      - "0" / "1" to filter to that label
      - "" to filter to unlabeled
      - None to disable filtering (export all)
    """

    v = (label or "").strip().lower()
    if not v or v in {"all", "*"}:
        return None
    if v in {"unlabeled", "none", "null"}:
        return ""
    if v in {"0", "1"}:
        return v
    raise HTTPException(status_code=400, detail="label must be 0, 1, unlabeled, or all")


@router.get("/api/review/export_jsonl")
def review_export_jsonl(
    run_dir: str | None = Query(default=None),
    label: str | None = Query(default="1", description="0, 1, unlabeled, or all"),
):
    rd = _resolve_run_dir(run_dir)
    cache = _load_run_cache(rd)

    want = _export_label_filter(label)

    def gen():
        for row in cache.review_rows:
            qid = (row.get("query_id") or row.get("id") or "").strip()
            if not qid:
                continue
            if want is not None:
                have = (row.get("human_label") or "").strip()
                if want == "":
                    if have:
                        continue
                elif have != want:
                    continue

            payload = {"query_id": qid, "review_row": row, "generation": cache.generations_by_id.get(qid)}
            yield (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")

    filename = f"review_export.{Path(cache.run_dir).name}.label_{(label or 'all').strip()}.jsonl"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(gen(), media_type="application/x-ndjson", headers=headers)
