#!/usr/bin/env bash
set -euo pipefail
source .venv/bin/activate
export POSTGRES_SCHEMA=eval_revamp_combined_512_20260217
export FINRAG_DOC_INDEX_PATH="$(pwd)/data/ingest_profiles/eval_revamp_combined_512_20260217/sec_filings_md_secparser/chunked_512_64/doc_index.jsonl"
export MODE=normal
export RUN_PREFIX=reduced_heuristics_full_retry3_pinned
export GEN_WORKERS=12
export JUDGE_WORKERS=12
export QUERY_TIMEOUT_S=350
export QUERY_MAX_RETRIES=1
export JUDGE_CONTEXT_CHARS=80000
export JUDGE_TIMEOUT_S=350
export JUDGE_MAX_RETRIES=1
export PARALLEL_BACKEND=thread
bash scripts/run_full_eval_suite.sh
