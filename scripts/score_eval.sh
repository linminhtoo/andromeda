#!/bin/bash
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/_env.sh"

# NOTE: rmbr to set OPENAI_CHAT_BASE_URL in .env
export OPENAI_CHAT_MODEL="Qwen/Qwen3-VL-32B-Instruct-FP8"

now=$(date +"%Y%m%d_%H%M%S")
mkdir -p logs/
#   --run-dir ./eval/results/20251231_180206/eval_run.legacy_baseline_8workers.20251231_180206 \
python3 -m scripts.score_eval \
  --run-dir ./eval/results_v2/20251231_210651/eval_run.legacy_baseline_v2.20251231_210651 \
  --judge-workers 16 \
  --judge-provider openai \
  --judge-model "${OPENAI_CHAT_MODEL}" \
  --judge-base-url "${OPENAI_CHAT_BASE_URL}" \
  --judge-context-chars 65000 \
  2>&1 | tee logs/score_eval_${now}.log
