#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"

source .venv/bin/activate
set -a
. ./.env
set +a

export HOME=/tmp

OUT_ROOT="eval/results_revamp/adaptive_retrieval_budget_20260218"
RUNS_DIR="${OUT_ROOT}/runs"
mkdir -p "${RUNS_DIR}"

QUERY_SINGLE="eval/eval_queries_combined512_single_balanced100_validated_tol05_20260217.jsonl"

POSTGRES_SCHEMA_USE="${FRONTIER_POSTGRES_SCHEMA:-eval_revamp_combined_512_20260217}"
DOC_INDEX_PATH_USE="${FRONTIER_DOC_INDEX_PATH:-$ROOT/data/ingest_profiles/eval_revamp_combined_512_20260217/sec_filings_md_secparser/chunked_512_64/doc_index.jsonl}"

export POSTGRES_SCHEMA="${POSTGRES_SCHEMA_USE}"
export FINRAG_DOC_INDEX_PATH="${DOC_INDEX_PATH_USE}"

MANIFEST="${OUT_ROOT}/manifest_single100.csv"
echo "label,adaptive_budget,run_dir" > "${MANIFEST}"

append_manifest_row() {
  local label="$1"
  local adaptive_budget="$2"
  local run_dir="$3"
  python - "${MANIFEST}" "${label}" "${adaptive_budget}" "${run_dir}" <<'PY'
import csv
import sys

manifest_path = sys.argv[1]
row = sys.argv[2:]
with open(manifest_path, "a", encoding="utf-8", newline="") as handle:
    csv.writer(handle).writerow(row)
PY
}

run_one() {
  local label="$1"
  local adaptive_budget="$2"
  local run_name="single100_${label}"

  FINRAG_ENABLE_ADAPTIVE_RETRIEVAL_BUDGET="${adaptive_budget}" \
    python -m scripts.run_eval \
      --eval-queries "${QUERY_SINGLE}" \
      --out-dir "${RUNS_DIR}" \
      --run-name "${run_name}" \
      --mode normal \
      --enable-refine 0 \
      --concurrency 12 \
      --parallel-backend thread \
      --query-timeout-s 350 \
      --query-max-retries 1

  local run_dir
  run_dir=$(ls -td "${RUNS_DIR}"/eval_run.${run_name}.* | head -n1)

  FINRAG_ENABLE_ADAPTIVE_RETRIEVAL_BUDGET="${adaptive_budget}" \
    python -m scripts.score_eval \
      --run-dir "${run_dir}" \
      --judge-workers 12 \
      --judge-context-chars 80000 \
      --judge-timeout-s 350 \
      --judge-max-retries 1

  append_manifest_row "${label}" "${adaptive_budget}" "${run_dir}"
}

run_one "adaptive_off" "0"
run_one "adaptive_on" "1"

python agent_logs/scripts/eval/20260218_105900_collect_adaptive_retrieval_budget_single100.py \
  --manifest "${MANIFEST}" \
  --out-dir "${OUT_ROOT}"

echo "Wrote benchmark manifest: ${MANIFEST}"
