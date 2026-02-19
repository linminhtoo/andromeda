#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/_env.sh"

script_dir="$(
  cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1
  pwd
)"
project_root="$(
  cd -- "$script_dir/.." >/dev/null 2>&1
  pwd
)"
cd "$project_root"

if [[ -d ".venv" ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

PLANNER_QUERIES="${PLANNER_QUERIES:-eval/eval_queries_planner_characteristics_manual100_20260219.jsonl}"
OUT_ROOT="${OUT_ROOT:-eval/results_planner}"
RUN_PREFIX="${RUN_PREFIX:-planner_characteristics}"
STAMP="$(date +"%Y%m%d_%H%M%S")"
RUN_NAME="${RUN_PREFIX}_${STAMP}"

CONCURRENCY="${CONCURRENCY:-12}"
QUERY_TIMEOUT_S="${QUERY_TIMEOUT_S:-350}"
QUERY_MAX_RETRIES="${QUERY_MAX_RETRIES:-1}"
MAX_ITEMS="${MAX_ITEMS:-}"

mkdir -p "$OUT_ROOT"

if [[ ! -f "$PLANNER_QUERIES" ]]; then
  echo "Planner query file missing, generating at: $PLANNER_QUERIES"
  python -m scripts.make_planner_eval_set --out "$PLANNER_QUERIES"
fi

run_cmd=(
  python -m scripts.run_planner_eval
  --eval-queries "$PLANNER_QUERIES"
  --out-dir "$OUT_ROOT"
  --run-name "$RUN_NAME"
  --concurrency "$CONCURRENCY"
  --query-timeout-s "$QUERY_TIMEOUT_S"
  --query-max-retries "$QUERY_MAX_RETRIES"
)
if [[ -n "$MAX_ITEMS" ]]; then
  run_cmd+=(--max-items "$MAX_ITEMS")
fi

echo "=== Running planner evaluation (${RUN_NAME}) ==="
"${run_cmd[@]}"

run_dir="$(ls -td "${OUT_ROOT}/planner_eval_run.${RUN_NAME}."* | head -n 1)"
if [[ -z "$run_dir" ]]; then
  echo "Failed to resolve planner run directory for ${RUN_NAME}" >&2
  exit 1
fi

echo "=== Scoring planner evaluation (${run_dir}) ==="
python -m scripts.score_planner_eval --run-dir "$run_dir"

echo
echo "Planner run complete:"
echo "  run_dir: ${run_dir}"
echo "  summary: ${run_dir}/planner_score_summary.json"
echo "  review:  ${run_dir}/planner_review.csv"
