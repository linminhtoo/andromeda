#!/usr/bin/env bash
set -euo pipefail

cd /home/mlin/repos/z_scratch/financial-rag
source .venv/bin/activate
set -a
. ./.env
set +a

# EdgarTools cache path must be writable in this sandbox.
export HOME=/tmp

PROFILE="eval_revamp_20260216"
SEC_ROOT="data/ingest_profiles/${PROFILE}/sec_filings"
MD_ROOT="data/ingest_profiles/${PROFILE}/sec_filings_md_secparser"
CHUNK_ROOT="${MD_ROOT}/chunked_1024_128"

python3 -m scripts.download \
  --ingest-profile "${PROFILE}" \
  --tickers AMD NVDA INTC MU GOOGL AAPL MSFT AMZN META TSLA \
  --per-company 5 \
  --year-cutoff 2025 \
  --delay 0.15 \
  --skip-existing

python3 -m scripts.process_html_to_markdown \
  --ingest-profile "${PROFILE}" \
  --html-dir "${SEC_ROOT}/raw_htmls" \
  --meta-dir "${SEC_ROOT}/meta" \
  --recursive \
  --overwrite \
  --continue-on-error

python3 -m scripts.chunk \
  --ingest-profile "${PROFILE}" \
  --markdown-dir "${MD_ROOT}/processed_markdown" \
  --output-dir "${CHUNK_ROOT}" \
  --recursive \
  --overwrite \
  --doc-id-strategy stem \
  --chunker markdown_table_preserving \
  --max-tokens 1024 \
  --overlap-tokens 128 \
  --company-name-resolver none

python3 -m scripts.build_index \
  --ingest-profile "${PROFILE}" \
  --ingest-output-dir "${CHUNK_ROOT}" \
  --postgres-schema "${PROFILE}" \
  --context none \
  --batch-size 128 \
  --sparse-search-method bm25 \
  --debug-sample-rate 0 \
  --reset-corpus \
  --recreate-ann-index
