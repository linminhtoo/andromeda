#!/usr/bin/env bash
set -euo pipefail

cd /home/mlin/repos/z_scratch/financial-rag
source .venv/bin/activate
set -a
. ./.env
set +a

export HOME=/tmp

PROFILE="eval_revamp_combined_512_20260217"
SCHEMA="${PROFILE}"
TARGET_MD_DIR="data/ingest_profiles/${PROFILE}/sec_filings_md_secparser/processed_markdown"
TARGET_CHUNK_DIR="data/ingest_profiles/${PROFILE}/sec_filings_md_secparser/chunked_512_64"

SRC_MD_A="data/ingest_profiles/eval_revamp_20260216/sec_filings_md_secparser/processed_markdown"
SRC_MD_B="data/ingest_profiles/exp__chunk_1024_o128_tokenizer__ctx_none__index_m24_ef200/sec_filings_md_secparser/processed_markdown"

mkdir -p "${TARGET_MD_DIR}"

rsync -a --ignore-existing "${SRC_MD_A}/" "${TARGET_MD_DIR}/"
rsync -a --ignore-existing "${SRC_MD_B}/" "${TARGET_MD_DIR}/"

python - <<'PY'
from pathlib import Path

md = Path('data/ingest_profiles/eval_revamp_combined_512_20260217/sec_filings_md_secparser/processed_markdown')
files = sorted(md.glob('*.md'))
tickers = sorted({p.name.split('_', 1)[0].upper() for p in files if '_' in p.name})
print('merged_markdown_files', len(files))
print('merged_tickers', len(tickers), ' '.join(tickers))
PY

python -m scripts.chunk \
  --ingest-profile "${PROFILE}" \
  --markdown-dir "${TARGET_MD_DIR}" \
  --output-dir "${TARGET_CHUNK_DIR}" \
  --recursive \
  --overwrite \
  --doc-id-strategy stem \
  --chunker markdown_table_preserving \
  --max-tokens 512 \
  --overlap-tokens 64 \
  --company-name-resolver none

python -m scripts.build_index \
  --ingest-profile "${PROFILE}" \
  --ingest-output-dir "${TARGET_CHUNK_DIR}" \
  --postgres-schema "${SCHEMA}" \
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
