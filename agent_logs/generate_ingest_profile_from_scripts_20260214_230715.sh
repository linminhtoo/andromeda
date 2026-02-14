#!/usr/bin/env bash
set -euo pipefail

script_dir="$(
  cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1
  pwd
)"
project_root="$(
  cd -- "$script_dir/.." >/dev/null 2>&1
  pwd
)"

cd "$project_root"
source .venv/bin/activate
source scripts/_env.sh

python - <<'PY'
from __future__ import annotations

import json
import os
from pathlib import Path

from finrag.ingest_profile import (
    ingest_profile_path,
    resolve_ingest_profile_name,
    update_ingest_profile_step,
)


def env_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def env_bool(name: str, default: bool = False) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "y", "on"}:
        return True
    if raw in {"0", "false", "no", "n", "off"}:
        return False
    return default


def resolve_path(project_root: Path, value: str) -> str:
    path = Path(os.path.expanduser(value))
    if not path.is_absolute():
        path = (project_root / path).resolve()
    return str(path)


project_root = Path.cwd().resolve()
profile_name = resolve_ingest_profile_name(None)

chunk_max_tokens = env_int("CHUNK_MAX_TOKENS", 1024)
chunk_overlap_tokens = env_int("CHUNK_OVERLAP_TOKENS", 128)
chunk_output_override = (os.getenv("CHUNK_OUTPUT_DIR") or "").strip()
if chunk_output_override:
    chunk_output_dir = resolve_path(project_root, chunk_output_override)
else:
    chunk_output_dir = str(
        (project_root / f"data/sec_filings_md_secparser/chunked_{chunk_max_tokens}_{chunk_overlap_tokens}").resolve()
    )

postgres_dsn = (os.getenv("POSTGRES_DSN") or os.getenv("DATABASE_URL") or "").strip() or None
postgres_schema = (os.getenv("POSTGRES_SCHEMA") or "").strip() or None
openai_embed_base_url = (os.getenv("OPENAI_EMBED_BASE_URL") or "").strip() or None
openai_context_base_url = (os.getenv("OPENAI_CONTEXT_BASE_URL") or "").strip() or None

context_strategy = (os.getenv("CONTEXT_STRATEGY") or "neighbors").strip() or "neighbors"
context_window = env_int("CONTEXT_WINDOW", 1)
context_max_tokens = env_int("CONTEXT_MAX_TOKENS", 256)
context_max_concurrency = env_int("CONTEXT_MAX_CONCURRENCY", 64)
batch_size = env_int("INDEX_BATCH_SIZE", 256)

ann_hnsw_m_raw = (os.getenv("ANN_HNSW_M") or "").strip()
ann_hnsw_ef_raw = (os.getenv("ANN_HNSW_EF_CONSTRUCTION") or "").strip()
ann_hnsw_m = int(ann_hnsw_m_raw) if ann_hnsw_m_raw else None
ann_hnsw_ef = int(ann_hnsw_ef_raw) if ann_hnsw_ef_raw else None

sparse_search_method = (
    (os.getenv("POSTGRES_SPARSE_SEARCH_METHOD") or os.getenv("SPARSE_SEARCH_METHOD") or "bm25").strip().lower()
    or "bm25"
)

update_ingest_profile_step(
    project_root=project_root,
    profile_name=profile_name,
    step_name="download",
    settings={
        "tickers": ["APH", "GOOGL", "NVDA", "AMD", "TER", "LITE", "SNDK", "MU"],
        "output_dir": str((project_root / "data/sec_filings").resolve()),
        "per_company": 10,
        "delay": 0.2,
        "skip_existing": True,
        "ingest_profile": None,
    },
    metadata={
        "generated_without_execution": True,
        "source": "scripts/download.sh",
        "raw_html_dir": str((project_root / "data/sec_filings/raw_htmls").resolve()),
        "meta_dir": str((project_root / "data/sec_filings/meta").resolve()),
    },
)

update_ingest_profile_step(
    project_root=project_root,
    profile_name=profile_name,
    step_name="process_html_to_markdown",
    settings={
        "html_dir": str((project_root / "data/sec_filings/raw_htmls").resolve()),
        "output_dir": str((project_root / "data/sec_filings_md_secparser").resolve()),
        "ingest_profile": None,
        "meta_dir": str((project_root / "data/sec_filings/meta").resolve()),
        "pattern": "*.htm*",
        "recursive": True,
        "year_cutoff": 2023,
        "max_files": None,
        "overwrite": False,
        "include_irrelevant_elements": False,
        "parser_mode": "auto",
        "continue_on_error": True,
    },
    metadata={
        "generated_without_execution": True,
        "source": "scripts/process_html_to_markdown.sh",
        "output_root": str((project_root / "data/sec_filings_md_secparser").resolve()),
    },
)

update_ingest_profile_step(
    project_root=project_root,
    profile_name=profile_name,
    step_name="chunk",
    settings={
        "markdown_dir": str((project_root / "data/sec_filings_md_secparser/processed_markdown").resolve()),
        "output_dir": chunk_output_dir,
        "ingest_profile": profile_name,
        "metadata_dir": str((project_root / "data/sec_filings_md_secparser/debug").resolve()),
        "pattern": "*.md",
        "recursive": True,
        "max_files": None,
        "year_cutoff": None,
        "overwrite": False,
        "doc_id_strategy": "uuid",
        "chunker": (os.getenv("CHUNKER_NAME") or "markdown_table_preserving").strip() or "markdown_table_preserving",
        "split_markdown_tables": False,
        "hf_offline": False,
        "tokenizer_model": "sentence-transformers/all-MiniLM-L6-v2",
        "max_tokens": chunk_max_tokens,
        "overlap_tokens": chunk_overlap_tokens,
        "preprocess_markdown_tables": True,
        "markdown_table_fence_lang": "table",
        "section_neighbor_window": 2,
        "max_summary_chars": 300,
        "company_name_resolver": "yahoo",
    },
    metadata={
        "generated_without_execution": True,
        "source": "scripts/chunk.sh",
        "doc_index_path": str((Path(chunk_output_dir) / "doc_index.jsonl").resolve()),
    },
)

update_ingest_profile_step(
    project_root=project_root,
    profile_name=profile_name,
    step_name="build_index",
    settings={
        "ingest_output_dir": "./data/sec_filings_md_secparser/chunked_1024_128",
        "ingest_profile": profile_name,
        "postgres_dsn": postgres_dsn,
        "postgres_schema": postgres_schema,
        "llm_provider": "openai",
        "contextual_llm_provider": "openai",
        "dense_model": "BAAI/bge-m3",
        "contextual_model": "Qwen/Qwen3-VL-32B-Instruct-FP8",
        "dense_base_url": openai_embed_base_url,
        "contextual_base_url": openai_context_base_url,
        "max_docs": None,
        "batch_size": batch_size,
        "context": context_strategy,
        "context_window": context_window,
        "context_metadata_key": "retrieval_context",
        "context_max_tokens": context_max_tokens,
        "context_max_concurrency": context_max_concurrency,
        "ann_hnsw_m": ann_hnsw_m,
        "ann_hnsw_ef_construction": ann_hnsw_ef,
        "sparse_search_method": sparse_search_method,
        "debug_sample_rate": env_float("DEBUG_SAMPLE_RATE", 0.02),
        "debug_max_samples": env_int("DEBUG_MAX_SAMPLES", 100),
        "debug_sample_seed": env_int("DEBUG_SAMPLE_SEED", 42),
        "reset_corpus": env_bool("RESET_CORPUS", False),
        "recreate_ann_index": env_bool("RECREATE_ANN_INDEX", False),
        "allow_default_schema_mutations": env_bool("ALLOW_DEFAULT_SCHEMA_MUTATIONS", False),
        "skip_existing_chunks": False,
    },
    metadata={
        "generated_without_execution": True,
        "source": "scripts/build_index.sh",
    },
)

profile_path = ingest_profile_path(project_root, profile_name)
print(json.dumps({"profile_name": profile_name, "profile_path": str(profile_path)}, indent=2))
PY
