#!/usr/bin/env bash
set -euo pipefail

cd /home/mlin/repos/z_scratch/financial-rag
source .venv/bin/activate
set -a
. ./.env
set +a

PROFILE="eval_revamp_20260216"
CHUNK_ROOT="data/ingest_profiles/${PROFILE}/sec_filings_md_secparser/chunked_1024_128"

python3 -m scripts.build_index \
  --ingest-profile "${PROFILE}" \
  --ingest-output-dir "${CHUNK_ROOT}" \
  --postgres-schema "${PROFILE}" \
  --postgres-dsn "${POSTGRES_DSN:-${DATABASE_URL:-}}" \
  --llm-provider openai \
  --dense-model "BAAI/bge-m3" \
  --dense-base-url "${OPENAI_EMBED_BASE_URL:-}" \
  --context none \
  --batch-size 128 \
  --sparse-search-method bm25 \
  --debug-sample-rate 0 \
  --reset-corpus \
  --recreate-ann-index
