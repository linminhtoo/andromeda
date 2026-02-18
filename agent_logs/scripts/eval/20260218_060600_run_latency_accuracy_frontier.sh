#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"

source .venv/bin/activate
set -a
. ./.env
set +a

export HOME=/tmp

OUT_ROOT="eval/results_revamp/latency_accuracy_frontier_20260218"
RUNS_DIR="${OUT_ROOT}/runs"
mkdir -p "${RUNS_DIR}"

QUERY_SINGLE="eval/eval_queries_combined512_single_balanced100_validated_tol05_20260217.jsonl"
QUERY_MULTI="eval/eval_queries_combined512_multi_comparison60_validated_tol05_20260217.jsonl"
# Use dedicated frontier overrides so generic .env defaults do not silently
# redirect this study to unrelated schemas/profiles.
POSTGRES_SCHEMA_USE="${FRONTIER_POSTGRES_SCHEMA:-eval_revamp_combined_512_20260217}"
DOC_INDEX_PATH_USE="${FRONTIER_DOC_INDEX_PATH:-$ROOT/data/ingest_profiles/eval_revamp_combined_512_20260217/sec_filings_md_secparser/chunked_512_64/doc_index.jsonl}"

export POSTGRES_SCHEMA="${POSTGRES_SCHEMA_USE}"
export FINRAG_DOC_INDEX_PATH="${DOC_INDEX_PATH_USE}"

MANIFEST="${OUT_ROOT}/frontier_manifest.csv"
echo "exp_id,axis,setting,notes,single_run_dir,multi_run_dir" > "${MANIFEST}"

append_manifest_row() {
  local exp_id="$1"
  local axis="$2"
  local setting="$3"
  local notes="$4"
  local single_run_dir="$5"
  local multi_run_dir="$6"

  python - "${MANIFEST}" "${exp_id}" "${axis}" "${setting}" "${notes}" "${single_run_dir}" "${multi_run_dir}" <<'PY'
import csv
import sys

manifest_path = sys.argv[1]
row = sys.argv[2:]

with open(manifest_path, "a", encoding="utf-8", newline="") as handle:
    writer = csv.writer(handle)
    writer.writerow(row)
PY
}

run_one() {
  local exp_id="$1"
  local axis="$2"
  local setting="$3"
  local notes="$4"
  shift 4
  local -a extra_args=("$@")

  local single_run_name="single100_${exp_id}"
  local multi_run_name="multi60_${exp_id}"

  echo "=== ${exp_id}: single suite ==="
  python -m scripts.run_eval \
    --eval-queries "${QUERY_SINGLE}" \
    --out-dir "${RUNS_DIR}" \
    --run-name "${single_run_name}" \
    --mode normal \
    --enable-refine 0 \
    --concurrency 12 \
    --parallel-backend thread \
    --query-timeout-s 350 \
    --query-max-retries 1 \
    "${extra_args[@]}"

  local single_run_dir
  single_run_dir=$(ls -td "${RUNS_DIR}"/eval_run.${single_run_name}.* | head -n1)
  echo "SINGLE_RUN_DIR=${single_run_dir}"

  python -m scripts.score_eval \
    --run-dir "${single_run_dir}" \
    --judge-workers 12 \
    --judge-context-chars 80000 \
    --judge-timeout-s 350 \
    --judge-max-retries 1

  echo "=== ${exp_id}: multi suite ==="
  python -m scripts.run_eval \
    --eval-queries "${QUERY_MULTI}" \
    --out-dir "${RUNS_DIR}" \
    --run-name "${multi_run_name}" \
    --mode normal \
    --enable-refine 0 \
    --concurrency 12 \
    --parallel-backend thread \
    --query-timeout-s 350 \
    --query-max-retries 1 \
    "${extra_args[@]}"

  local multi_run_dir
  multi_run_dir=$(ls -td "${RUNS_DIR}"/eval_run.${multi_run_name}.* | head -n1)
  echo "MULTI_RUN_DIR=${multi_run_dir}"

  python -m scripts.score_eval \
    --run-dir "${multi_run_dir}" \
    --judge-workers 12 \
    --judge-context-chars 80000 \
    --judge-timeout-s 350 \
    --judge-max-retries 1

  append_manifest_row "${exp_id}" "${axis}" "${setting}" "${notes}" "${single_run_dir}" "${multi_run_dir}"
}

# Baseline
run_one \
  "baseline_normal" \
  "baseline" \
  "normal_default" \
  "normal preset defaults; tools enabled; no refine"

# Axis 1: answering effort
run_one \
  "effort_low" \
  "answering_effort" \
  "low" \
  "answering effort low" \
  --answering-effort low

run_one \
  "effort_high" \
  "answering_effort" \
  "high" \
  "answering effort high" \
  --answering-effort high

# Axis 2: retrieval depth
run_one \
  "retrieve_low_30_18" \
  "retrieval_depth" \
  "top_k_retrieve=30,top_k_rerank=18" \
  "lower retrieval/rerank depth" \
  --top-k-retrieve 30 \
  --top-k-rerank 18

run_one \
  "retrieve_high_60_35" \
  "retrieval_depth" \
  "top_k_retrieve=60,top_k_rerank=35" \
  "higher retrieval/rerank depth" \
  --top-k-retrieve 60 \
  --top-k-rerank 35

# Axis 3: generation budget / decoding behavior
run_one \
  "temperature_0" \
  "generation_behavior" \
  "draft_temperature=0.0" \
  "deterministic draft decoding" \
  --draft-temperature 0.0

run_one \
  "tight_tokens_32k_16k" \
  "generation_budget" \
  "draft_max_tokens=32768,final_max_tokens=16384" \
  "tighter token budget" \
  --draft-max-tokens 32768 \
  --final-max-tokens 16384

python agent_logs/scripts/eval/20260218_060700_collect_latency_accuracy_frontier.py \
  --manifest "${MANIFEST}" \
  --out-dir "${OUT_ROOT}"

echo "Wrote manifest: ${MANIFEST}"
