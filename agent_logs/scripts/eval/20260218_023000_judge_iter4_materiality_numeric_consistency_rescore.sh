#!/usr/bin/env bash
set -euo pipefail

source .venv/bin/activate
set -a
. ./.env
set +a

SRC_OPEN="eval/results_revamp/open/eval_run.open_diverse200_iter0_baseline_normal_tools12_norefine_qt350_jt350.20260218_002122"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT_ROOT="eval/results_revamp/judge_tuning"
OUT_OPEN="${OUT_ROOT}/eval_run.open200_judge_iter4_materiality_numeric_consistency.${STAMP}"

mkdir -p "$OUT_OPEN"
cp "$SRC_OPEN/eval_queries.jsonl" "$OUT_OPEN/eval_queries.jsonl"
cp "$SRC_OPEN/generations.jsonl" "$OUT_OPEN/generations.jsonl"

python scripts/score_eval.py \
  --run-dir "$OUT_OPEN" \
  --judge-workers 12 \
  --judge-context-chars 80000 \
  --judge-timeout-s 350 \
  --judge-max-retries 1 \
  --kinds open_ended

printf "OUT_OPEN=%s\n" "$OUT_OPEN"
