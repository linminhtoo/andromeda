#!/usr/bin/env bash
set -euo pipefail
source .venv/bin/activate

RUN_SINGLE="eval/results_revamp/full_suite/eval_run.reduced_heuristics_full_retry4_envoverride_20260218_195034.single100.normal.tools12.norefine.20260218_195034"
RUN_MULTI="eval/results_revamp/full_suite/eval_run.reduced_heuristics_full_retry4_envoverride_20260218_195034.multi60.normal.tools12.norefine.20260218_200838"
RUN_OPEN="eval/results_revamp/full_suite/eval_run.reduced_heuristics_full_retry4_envoverride_20260218_195034.open200.normal.tools12.norefine.20260218_202301"

AUDIT_DIR="eval/results_revamp/full_suite/reduced_heuristics_full_retry4_envoverride_20260218_195034.judge_audit"
mkdir -p "$AUDIT_DIR"

python -m scripts.judge_reliability build-audit \
  --run-dirs "$RUN_SINGLE" "$RUN_MULTI" "$RUN_OPEN" \
  --out-csv "$AUDIT_DIR/decision_audit.raw.csv"

python -m scripts.audit_judge_decisions \
  --audit-csv "$AUDIT_DIR/decision_audit.raw.csv" \
  --out-csv "$AUDIT_DIR/decision_audit.audited.csv" \
  --workers 12 \
  --context-chars 80000 \
  --timeout-s 350 \
  --max-retries 1 \
  --overwrite

python -m scripts.judge_reliability evaluate \
  --audit-csv "$AUDIT_DIR/decision_audit.audited.csv" \
  --out-json "$AUDIT_DIR/judge_reliability_report.json" \
  --dev-fraction 0.75 \
  --seed 42 \
  --n-bootstrap 2000 \
  --write-split
