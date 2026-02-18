#!/usr/bin/env bash
set -euo pipefail

source .venv/bin/activate
set -a
. ./.env
set +a

SRC_OPEN="eval/results_revamp/open/eval_run.openended_chunk512_pool100_tools12_norefine_partial71_curated.20260217_200305"
SRC_SINGLE="eval/results_revamp/single/eval_run.single_ext_chunk512_v1_normal_tools12_norefine_eval100.20260217_043752"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT_ROOT="eval/results_revamp/judge_tuning"
OUT_OPEN="${OUT_ROOT}/eval_run.open71_judge_iter1_materiality.${STAMP}"
OUT_SINGLE="${OUT_ROOT}/eval_run.single100_judge_iter1_materiality.${STAMP}"

mkdir -p "$OUT_OPEN" "$OUT_SINGLE"
cp "$SRC_OPEN/eval_queries.jsonl" "$OUT_OPEN/eval_queries.jsonl"
cp "$SRC_OPEN/generations.jsonl" "$OUT_OPEN/generations.jsonl"
cp "$SRC_SINGLE/eval_queries.jsonl" "$OUT_SINGLE/eval_queries.jsonl"
cp "$SRC_SINGLE/generations.jsonl" "$OUT_SINGLE/generations.jsonl"

python scripts/score_eval.py \
  --run-dir "$OUT_OPEN" \
  --judge-workers 8 \
  --judge-context-chars 80000 \
  --judge-timeout-s 300 \
  --judge-max-retries 1 \
  --kinds open_ended

python scripts/score_eval.py \
  --run-dir "$OUT_SINGLE" \
  --judge-workers 8 \
  --judge-context-chars 80000 \
  --judge-timeout-s 300 \
  --judge-max-retries 1

printf "OUT_OPEN=%s\n" "$OUT_OPEN"
printf "OUT_SINGLE=%s\n" "$OUT_SINGLE"
