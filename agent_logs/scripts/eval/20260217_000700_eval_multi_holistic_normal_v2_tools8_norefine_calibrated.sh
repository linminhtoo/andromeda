#!/usr/bin/env bash
set -euo pipefail

cd /home/mlin/repos/z_scratch/financial-rag
source .venv/bin/activate
set -a
. ./.env
set +a

export HOME=/tmp
export POSTGRES_SCHEMA="eval_revamp_20260216"
export FINRAG_DOC_INDEX_PATH="/home/mlin/repos/z_scratch/financial-rag/data/ingest_profiles/eval_revamp_20260216/sec_filings_md_secparser/chunked_1024_128/doc_index.jsonl"
export FINRAG_ENABLE_MMR_DIVERSITY=0

OUT_DIR="eval/results_revamp/multi"
mkdir -p "${OUT_DIR}"

python3 -m scripts.run_eval \
  --eval-queries "eval/eval_queries_revamp_multi_comparison_validated_tol05_20260216.jsonl" \
  --out-dir "${OUT_DIR}" \
  --run-name "multi_holistic_normal_v2_tools8_norefine_calibrated" \
  --mode normal \
  --enable-refine 0 \
  --concurrency 8 \
  --parallel-backend thread \
  --query-timeout-s 360

RUN_DIR=$(ls -td "${OUT_DIR}"/eval_run.multi_holistic_normal_v2_tools8_norefine_calibrated.* | head -n1)
echo "RUN_DIR=${RUN_DIR}"

python3 -m scripts.score_eval \
  --run-dir "${RUN_DIR}" \
  --judge-workers 6 \
  --judge-provider openai \
  --judge-model "${OPENAI_CHAT_MODEL}" \
  --judge-base-url "${OPENAI_CHAT_BASE_URL}" \
  --judge-context-chars 80000

python3 - <<'PY'
import glob
import json
path = sorted(glob.glob('eval/results_revamp/multi/eval_run.multi_holistic_normal_v2_tools8_norefine_calibrated.*/score_summary.json'))[-1]
print('score_summary_path', path)
print(json.dumps(json.load(open(path)), indent=2))
PY
