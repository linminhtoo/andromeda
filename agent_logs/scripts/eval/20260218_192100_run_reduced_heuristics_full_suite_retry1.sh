#!/usr/bin/env bash
set -euo pipefail
source .venv/bin/activate
export MODE=normal
export RUN_PREFIX=reduced_heuristics_full_retry1
export GEN_WORKERS=12
export JUDGE_WORKERS=12
export QUERY_TIMEOUT_S=350
export QUERY_MAX_RETRIES=1
export JUDGE_CONTEXT_CHARS=80000
export JUDGE_TIMEOUT_S=350
export JUDGE_MAX_RETRIES=1
export PARALLEL_BACKEND=thread
bash scripts/run_full_eval_suite.sh
