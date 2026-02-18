#!/usr/bin/env bash
set -euo pipefail

cd /home/mlin/repos/z_scratch/financial-rag
source .venv/bin/activate
set -a
. ./.env
set +a

BASE_RUN="eval/results_revamp/single/eval_run.single_holistic_normal_v17_tools8_norefine_revertprompt.20260216_233713"
STAMP=$(date +%Y%m%d_%H%M%S)
OUT_RUN="eval/results_revamp/single/eval_run.single_holistic_normal_v17_tools8_norefine_revertprompt_rescore_harness_v3.${STAMP}"

mkdir -p "${OUT_RUN}"
cp "${BASE_RUN}/eval_queries.jsonl" "${OUT_RUN}/eval_queries.jsonl"
cp "${BASE_RUN}/generations.jsonl" "${OUT_RUN}/generations.jsonl"
cp "${BASE_RUN}/run_config.json" "${OUT_RUN}/run_config.json"
cp "${BASE_RUN}/generation_summary.json" "${OUT_RUN}/generation_summary.json"

python3 -m scripts.score_eval \
  --run-dir "${OUT_RUN}" \
  --judge-workers 6 \
  --judge-provider openai \
  --judge-model "${OPENAI_CHAT_MODEL}" \
  --judge-base-url "${OPENAI_CHAT_BASE_URL}" \
  --judge-context-chars 80000

python3 - <<'PY'
import glob
import json
path = sorted(glob.glob('eval/results_revamp/single/eval_run.single_holistic_normal_v17_tools8_norefine_revertprompt_rescore_harness_v3.*/score_summary.json'))[-1]
print('score_summary_path', path)
print(json.dumps(json.load(open(path)), indent=2))
PY
