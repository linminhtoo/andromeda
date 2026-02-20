#!/usr/bin/env bash
set -euo pipefail

source .venv/bin/activate

# Baseline-only full suite run (single100 + multi60 + open200)
# with fixed doc-index/profile guardrails from scripts/run_full_eval_suite.sh.
RUN_PREFIX="baseline_fixed_guardrails" \
RUN_OPEN_STRESS="1" \
bash scripts/run_full_eval_suite.sh
