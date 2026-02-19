#!/usr/bin/env bash
set -euo pipefail
source .venv/bin/activate
export ENV_FILE=/home/mlin/repos/z_scratch/financial-rag/agent_logs/scripts/eval/20260218_200300_reduced_heuristics_eval_override.env
export MODE=normal
export RUN_PREFIX=reduced_heuristics_full_retry4_envoverride
export GEN_WORKERS=12
export JUDGE_WORKERS=12
export QUERY_TIMEOUT_S=350
export QUERY_MAX_RETRIES=1
export JUDGE_CONTEXT_CHARS=80000
export JUDGE_TIMEOUT_S=350
export JUDGE_MAX_RETRIES=1
export PARALLEL_BACKEND=thread
bash scripts/run_full_eval_suite.sh
