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

POSTGRES_SCHEMA_USE="${FRONTIER_POSTGRES_SCHEMA:-eval_revamp_combined_512_20260217}"
DOC_INDEX_PATH_USE="${FRONTIER_DOC_INDEX_PATH:-$ROOT/data/ingest_profiles/eval_revamp_combined_512_20260217/sec_filings_md_secparser/chunked_512_64/doc_index.jsonl}"

export POSTGRES_SCHEMA="${POSTGRES_SCHEMA_USE}"
export FINRAG_DOC_INDEX_PATH="${DOC_INDEX_PATH_USE}"

MANIFEST="${OUT_ROOT}/frontier_manifest.csv"
if [[ ! -f "${MANIFEST}" ]]; then
  echo "exp_id,axis,setting,notes,single_run_dir,multi_run_dir" > "${MANIFEST}"
fi

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

if python - "$MANIFEST" <<'PY'
import csv
import sys

manifest_path = sys.argv[1]
exists = False
with open(manifest_path, "r", encoding="utf-8", newline="") as handle:
    reader = csv.reader(handle)
    next(reader, None)
    exists = any(row and row[0] == "mode_quick_true" for row in reader)
raise SystemExit(0 if exists else 1)
PY
then
  echo "mode_quick_true already present in manifest; skipping generation."
else
  python -m scripts.run_eval \
    --eval-queries "${QUERY_SINGLE}" \
    --out-dir "${RUNS_DIR}" \
    --run-name "single100_mode_quick_true" \
    --mode quick \
    --enable-refine 0 \
    --concurrency 12 \
    --parallel-backend thread \
    --query-timeout-s 350 \
    --query-max-retries 1

  single_run_dir=$(ls -td "${RUNS_DIR}"/eval_run.single100_mode_quick_true.* | head -n1)

  python -m scripts.score_eval \
    --run-dir "${single_run_dir}" \
    --judge-workers 12 \
    --judge-context-chars 80000 \
    --judge-timeout-s 350 \
    --judge-max-retries 1

  python -m scripts.run_eval \
    --eval-queries "${QUERY_MULTI}" \
    --out-dir "${RUNS_DIR}" \
    --run-name "multi60_mode_quick_true" \
    --mode quick \
    --enable-refine 0 \
    --concurrency 12 \
    --parallel-backend thread \
    --query-timeout-s 350 \
    --query-max-retries 1

  multi_run_dir=$(ls -td "${RUNS_DIR}"/eval_run.multi60_mode_quick_true.* | head -n1)

  python -m scripts.score_eval \
    --run-dir "${multi_run_dir}" \
    --judge-workers 12 \
    --judge-context-chars 80000 \
    --judge-timeout-s 350 \
    --judge-max-retries 1

  append_manifest_row \
    "mode_quick_true" \
    "preset_mode" \
    "quick" \
    "quick preset with correct --mode quick wiring" \
    "${single_run_dir}" \
    "${multi_run_dir}"
fi

python agent_logs/scripts/eval/20260218_060700_collect_latency_accuracy_frontier.py \
  --manifest "${MANIFEST}" \
  --out-dir "${OUT_ROOT}"

echo "Updated manifest: ${MANIFEST}"
