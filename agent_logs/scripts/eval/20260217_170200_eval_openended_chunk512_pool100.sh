#!/usr/bin/env bash
set -euo pipefail

cd /home/mlin/repos/z_scratch/financial-rag
source .venv/bin/activate
set -a
. ./.env
set +a

export HOME=/tmp
export FINRAG_INGEST_PROFILE="eval_revamp_combined_512_20260217"
export POSTGRES_SCHEMA="eval_revamp_combined_512_20260217"
export FINRAG_DOC_INDEX_PATH="/home/mlin/repos/z_scratch/financial-rag/data/ingest_profiles/eval_revamp_combined_512_20260217/sec_filings_md_secparser/chunked_512_64/doc_index.jsonl"

RUN_NAME="openended_chunk512_pool100_tools12_norefine"
OUT_ROOT="eval/results_revamp/open"

python -m scripts.run_eval \
  --eval-queries "eval/eval_queries_combined512_validated_tol05_20260217.jsonl" \
  --out-dir "${OUT_ROOT}" \
  --run-name "${RUN_NAME}" \
  --mode normal \
  --kinds open_ended \
  --max-items 100 \
  --concurrency 12 \
  --parallel-backend thread \
  --query-timeout-s 300 \
  --query-max-retries 1

RUN_DIR=$(ls -dt "${OUT_ROOT}"/eval_run."${RUN_NAME}".* | head -n 1)
echo "RUN_DIR=${RUN_DIR}"

python -m scripts.score_eval \
  --run-dir "${RUN_DIR}" \
  --judge-workers 12 \
  --judge-provider openai \
  --judge-model "${OPENAI_CHAT_MODEL}" \
  --judge-base-url "${OPENAI_CHAT_BASE_URL}" \
  --judge-context-chars 80000 \
  --judge-timeout-s 300 \
  --judge-max-retries 1
