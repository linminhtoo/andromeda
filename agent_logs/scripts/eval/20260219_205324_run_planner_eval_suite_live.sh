#!/usr/bin/env bash
set -euo pipefail

repo_root="$(
  cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." >/dev/null 2>&1
  pwd
)"
cd "$repo_root"

source .venv/bin/activate

CONCURRENCY=12 \
QUERY_TIMEOUT_S=350 \
QUERY_MAX_RETRIES=1 \
OUT_ROOT=eval/results_planner \
RUN_PREFIX=planner_live_manual100 \
bash scripts/run_planner_eval_suite.sh
