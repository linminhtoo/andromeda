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

python3 -m scripts.build_index \
  --ingest-output-dir ./data/sec_filings_md_v5/chunked_1024_128 \
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
  --skip-existing-chunks
