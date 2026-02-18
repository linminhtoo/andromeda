#!/usr/bin/env bash
set -euo pipefail

cd /home/mlin/repos/z_scratch/financial-rag
source .venv/bin/activate
set -a
. ./.env
set +a

export HOME=/tmp

BASE_PROFILE="eval_revamp_20260216"
STUDY_PROFILE="eval_chunksize_study_20260217"
BASE_MD_DIR="data/ingest_profiles/${BASE_PROFILE}/sec_filings_md_secparser/processed_markdown"
QUERY_SET="eval/eval_queries_revamp_single_balanced_validated_tol05_20260216.jsonl"

OUT_ROOT="eval/results_revamp/chunk_size_study"
RUNS_DIR="${OUT_ROOT}/runs"
mkdir -p "${RUNS_DIR}"

MANIFEST="${OUT_ROOT}/run_manifest.csv"
echo "chunk_size,overlap,schema,chunk_dir,run_dir" > "${MANIFEST}"

# size:overlap (fixed overlap ratio = 1/8)
for pair in "256:32" "512:64" "1024:128" "2048:256"; do
  size="${pair%%:*}"
  overlap="${pair##*:}"

  chunk_dir="data/ingest_profiles/${STUDY_PROFILE}/sec_filings_md_secparser/chunked_${size}_${overlap}"
  schema="eval_chunksize_${size}_20260217"

  echo "=== chunk size ${size} (overlap ${overlap}) ==="

  python -m scripts.chunk \
    --ingest-profile "${STUDY_PROFILE}" \
    --markdown-dir "${BASE_MD_DIR}" \
    --output-dir "${chunk_dir}" \
    --recursive \
    --overwrite \
    --doc-id-strategy stem \
    --chunker markdown_table_preserving \
    --max-tokens "${size}" \
    --overlap-tokens "${overlap}" \
    --company-name-resolver none

  python -m scripts.build_index \
    --ingest-profile "${STUDY_PROFILE}" \
    --ingest-output-dir "${chunk_dir}" \
    --postgres-schema "${schema}" \
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

  export POSTGRES_SCHEMA="${schema}"
  export FINRAG_DOC_INDEX_PATH="/home/mlin/repos/z_scratch/financial-rag/${chunk_dir}/doc_index.jsonl"

  python -m scripts.run_eval \
    --eval-queries "${QUERY_SET}" \
    --out-dir "${RUNS_DIR}" \
    --run-name "single_chunk${size}_normal_v13_eval50" \
    --mode normal \
    --enable-refine 0 \
    --concurrency 12 \
    --parallel-backend thread \
    --query-timeout-s 600

  run_dir=$(ls -td "${RUNS_DIR}"/eval_run.single_chunk${size}_normal_v13_eval50.* | head -n1)
  echo "RUN_DIR=${run_dir}"

  python -m scripts.score_eval \
    --run-dir "${run_dir}" \
    --judge-workers 8 \
    --judge-provider openai \
    --judge-model "${OPENAI_CHAT_MODEL}" \
    --judge-base-url "${OPENAI_CHAT_BASE_URL}" \
    --judge-context-chars 65000

  echo "${size},${overlap},${schema},${chunk_dir},${run_dir}" >> "${MANIFEST}"
done

python agent_logs/20260217_014500_collect_chunk_size_metrics.py \
  --manifest "${MANIFEST}" \
  --out-dir "${OUT_ROOT}"

echo "Wrote manifest: ${MANIFEST}"
