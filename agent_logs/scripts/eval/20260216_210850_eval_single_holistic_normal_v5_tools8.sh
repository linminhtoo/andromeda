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

OUT_DIR="eval/results_revamp/single"
mkdir -p "${OUT_DIR}"

python3 -m scripts.run_eval \
  --eval-queries "eval/eval_queries_revamp_single_balanced_validated_tol05_20260216.jsonl" \
  --out-dir "${OUT_DIR}" \
  --run-name "single_holistic_normal_v5_tools8" \
  --mode normal \
  --concurrency 8 \
  --parallel-backend thread \
  --query-timeout-s 90

RUN_DIR=$(ls -td "${OUT_DIR}"/eval_run.single_holistic_normal_v5_tools8.* | head -n1)
echo "RUN_DIR=${RUN_DIR}"

python3 -m scripts.score_eval \
  --run-dir "${RUN_DIR}" \
  --judge-workers 6 \
  --judge-provider openai \
  --judge-model "${OPENAI_CHAT_MODEL}" \
  --judge-base-url "${OPENAI_CHAT_BASE_URL}" \
  --judge-context-chars 65000

python3 - <<'PY'
import csv, glob, json
run=sorted(glob.glob('eval/results_revamp/single/eval_run.single_holistic_normal_v5_tools8.*'))[-1]
summary=json.load(open(f'{run}/score_summary.json'))
print('score_summary_path',f'{run}/score_summary.json')
print(json.dumps(summary,indent=2))

# quick tool-usage proxy from review.csv
review=list(csv.DictReader(open(f'{run}/review.csv',encoding='utf-8')))
print('review_rows',len(review))
PY
