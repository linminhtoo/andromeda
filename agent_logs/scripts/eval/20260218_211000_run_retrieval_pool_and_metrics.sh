#!/usr/bin/env bash
set -euo pipefail
source .venv/bin/activate

export HF_HOME="/tmp/hf_home"
export TRANSFORMERS_CACHE="/tmp/hf_home/transformers"
export HUGGINGFACE_HUB_CACHE="/tmp/hf_home/hub"
mkdir -p "$HF_HOME" "$TRANSFORMERS_CACHE" "$HUGGINGFACE_HUB_CACHE"

RUN_SINGLE="eval/results_revamp/full_suite/eval_run.reduced_heuristics_full_retry4_envoverride_20260218_195034.single100.normal.tools12.norefine.20260218_195034"
RUN_MULTI="eval/results_revamp/full_suite/eval_run.reduced_heuristics_full_retry4_envoverride_20260218_195034.multi60.normal.tools12.norefine.20260218_200838"
RUN_OPEN="eval/results_revamp/full_suite/eval_run.reduced_heuristics_full_retry4_envoverride_20260218_195034.open200.normal.tools12.norefine.20260218_202301"

NLI_MODEL="cross-encoder/nli-distilroberta-base"

# Retrieval/rerank metrics + NLI support snapshot for single100.
python scripts/eval_retrieval.py \
  --run-dir "$RUN_SINGLE" \
  --enable-nli \
  --nli-model "$NLI_MODEL" \
  --nli-max-open-ended 30 \
  --nli-batch-size 128

# Open-ended NLI support snapshot at scale (bounded sample for runtime).
python scripts/eval_retrieval.py \
  --run-dir "$RUN_OPEN" \
  --enable-nli \
  --nli-model "$NLI_MODEL" \
  --nli-max-open-ended 120 \
  --nli-batch-size 128

# Build pooled chunk labels for manual retrieval/rerank relevance audit.
python scripts/build_retrieval_label_pool.py \
  --run-dirs "$RUN_SINGLE" "$RUN_MULTI" "$RUN_OPEN" \
  --out-csv eval/results_revamp/full_suite/reduced_heuristics_full_retry4_envoverride_20260218_195034.retrieval_pool.csv \
  --out-json eval/results_revamp/full_suite/reduced_heuristics_full_retry4_envoverride_20260218_195034.retrieval_pool.stats.json \
  --pre-k 30 \
  --post-k 25 \
  --kinds factual open_ended comparison distractor
