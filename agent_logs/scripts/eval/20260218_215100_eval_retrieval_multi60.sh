#!/usr/bin/env bash
set -euo pipefail
source .venv/bin/activate
export HF_HOME=/tmp/hf_home
export TRANSFORMERS_CACHE=/tmp/hf_home/transformers
export HUGGINGFACE_HUB_CACHE=/tmp/hf_home/hub
mkdir -p "$HF_HOME" "$TRANSFORMERS_CACHE" "$HUGGINGFACE_HUB_CACHE"
python scripts/eval_retrieval.py \
  --run-dir eval/results_revamp/full_suite/eval_run.reduced_heuristics_full_retry4_envoverride_20260218_195034.multi60.normal.tools12.norefine.20260218_200838 \
  --enable-nli \
  --nli-model cross-encoder/nli-distilroberta-base \
  --nli-max-open-ended 120 \
  --nli-support-threshold 0.5 \
  --nli-contradiction-threshold 0.5 \
  --nli-batch-size 256
