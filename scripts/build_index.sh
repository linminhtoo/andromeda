#!/bin/bash
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/_env.sh"

if [[ -z "${POSTGRES_DSN:-${DATABASE_URL:-}}" ]]; then
  echo "Missing POSTGRES_DSN (or DATABASE_URL)." >&2
  exit 1
fi

script_dir="$(
  cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1
  pwd
)"
project_root="$(
  cd -- "$script_dir/.." >/dev/null 2>&1
  pwd
)"
cd "$project_root"

now=$(date +"%Y%m%d_%H%M%S")
ann_args=()
reset_args=()
if [[ -n "${ANN_HNSW_M:-}" ]]; then
  ann_args+=(--ann-hnsw-m "$ANN_HNSW_M")
fi
if [[ -n "${ANN_HNSW_EF_CONSTRUCTION:-}" ]]; then
  ann_args+=(--ann-hnsw-ef-construction "$ANN_HNSW_EF_CONSTRUCTION")
fi
if [[ "${RECREATE_ANN_INDEX:-0}" =~ ^(1|true|TRUE|yes|YES|on|ON)$ ]]; then
  ann_args+=(--recreate-ann-index)
fi
if [[ "${RESET_CORPUS:-0}" =~ ^(1|true|TRUE|yes|YES|on|ON)$ ]]; then
  reset_args+=(--reset-corpus)
fi

# REMEMBER TO CHANGE --ingest-output-dir
# NOTE: interrupted at 20/93 docs, will index the rest later (2.5 hours needed)
python3 -m scripts.build_index \
  --ingest-output-dir ./data/sec_filings_md_secparser/chunked_1024_128 \
  --postgres-dsn "${POSTGRES_DSN:-${DATABASE_URL:-}}" \
  --llm-provider openai \
  --dense-model BAAI/bge-m3 \
  --dense-base-url "${OPENAI_EMBED_BASE_URL:-}" \
  --contextual-llm-provider openai \
  --contextual-model "Qwen/Qwen3-VL-32B-Instruct-FP8" \
  --contextual-base-url "${OPENAI_CONTEXT_BASE_URL:-}" \
  --context neighbors \
  --context-window 8 \
  --context-max-concurrency 64 \
  --batch-size 128 \
  --skip-existing-chunks \
  "${reset_args[@]}" \
  "${ann_args[@]}" \
  2>&1 | tee "logs/build_index_${now}.log"
# Optional env flags:
#   RESET_CORPUS=true
#   RECREATE_ANN_INDEX=true
