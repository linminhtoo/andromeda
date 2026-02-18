#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"

source .venv/bin/activate
set -a
. ./.env
set +a

export HOME=/tmp

BASE_PROFILE="eval_revamp_combined_512_20260217"
BASE_MD_DIR="data/ingest_profiles/${BASE_PROFILE}/sec_filings_md_secparser/processed_markdown"

OUT_ROOT="eval/results_revamp/chunk_size_study_v2_expanded80k"
RUNS_DIR="${OUT_ROOT}/runs"
mkdir -p "${RUNS_DIR}"

QUERY_SINGLE="eval/eval_queries_combined512_single_balanced100_validated_tol05_20260217.jsonl"
QUERY_MULTI="eval/eval_queries_combined512_multi_comparison60_validated_tol05_20260217.jsonl"

MANIFEST="${OUT_ROOT}/run_manifest_expanded80k.csv"
echo "chunk_size,overlap,schema,chunk_dir,single_run_dir,multi_run_dir" > "${MANIFEST}"

# size:overlap (fixed overlap ratio = 1/8)
for pair in "256:32" "512:64" "1024:128" "2048:256"; do
  size="${pair%%:*}"
  overlap="${pair##*:}"

  profile="eval_chunksize_study_v2_${size}_20260218"
  chunk_dir="data/ingest_profiles/${profile}/sec_filings_md_secparser/chunked_${size}_${overlap}"
  schema="eval_chunksize_v2_${size}_20260218"

  echo "=== chunk size ${size} (overlap ${overlap}) ==="

  python -m scripts.chunk \
    --ingest-profile "${profile}" \
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
    --ingest-profile "${profile}" \
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
  export FINRAG_DOC_INDEX_PATH="${ROOT}/${chunk_dir}/doc_index.jsonl"

  python -m scripts.run_eval \
    --eval-queries "${QUERY_SINGLE}" \
    --out-dir "${RUNS_DIR}" \
    --run-name "single100_chunk${size}_normal_tools12_norefine_qt350" \
    --mode normal \
    --enable-refine 0 \
    --concurrency 12 \
    --parallel-backend thread \
    --query-timeout-s 350 \
    --query-max-retries 1

  single_run_dir=$(ls -td "${RUNS_DIR}"/eval_run.single100_chunk${size}_normal_tools12_norefine_qt350.* | head -n1)
  echo "SINGLE_RUN_DIR=${single_run_dir}"

  python -m scripts.score_eval \
    --run-dir "${single_run_dir}" \
    --judge-workers 12 \
    --judge-context-chars 80000 \
    --judge-timeout-s 350 \
    --judge-max-retries 1

  python -m scripts.run_eval \
    --eval-queries "${QUERY_MULTI}" \
    --out-dir "${RUNS_DIR}" \
    --run-name "multi60_chunk${size}_normal_tools12_norefine_qt350" \
    --mode normal \
    --enable-refine 0 \
    --concurrency 12 \
    --parallel-backend thread \
    --query-timeout-s 350 \
    --query-max-retries 1

  multi_run_dir=$(ls -td "${RUNS_DIR}"/eval_run.multi60_chunk${size}_normal_tools12_norefine_qt350.* | head -n1)
  echo "MULTI_RUN_DIR=${multi_run_dir}"

  python -m scripts.score_eval \
    --run-dir "${multi_run_dir}" \
    --judge-workers 12 \
    --judge-context-chars 80000 \
    --judge-timeout-s 350 \
    --judge-max-retries 1

  echo "${size},${overlap},${schema},${chunk_dir},${single_run_dir},${multi_run_dir}" >> "${MANIFEST}"
done

python agent_logs/scripts/eval/20260218_053900_collect_chunk_size_ablation_expanded80k.py \
  --manifest "${MANIFEST}" \
  --out-dir "${OUT_ROOT}"

echo "Wrote manifest: ${MANIFEST}"
