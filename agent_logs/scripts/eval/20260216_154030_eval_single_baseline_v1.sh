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
  --eval-queries "eval/eval_queries_revamp_20260216.jsonl" \
  --out-dir "${OUT_DIR}" \
  --run-name "single_baseline_v1" \
  --mode thinking \
  --concurrency 1 \
  --disable-finance-tools \
  --single-ticker-only \
  --max-items 40

RUN_DIR=$(ls -td "${OUT_DIR}"/eval_run.single_baseline_v1.* | head -n1)
echo "RUN_DIR=${RUN_DIR}"

python3 -m scripts.score_eval \
  --run-dir "${RUN_DIR}" \
  --single-ticker-only \
  --judge-workers 6 \
  --judge-provider openai \
  --judge-model "${OPENAI_CHAT_MODEL}" \
  --judge-base-url "${OPENAI_CHAT_BASE_URL}" \
  --judge-context-chars 65000

python3 - <<'PY'
import json,glob,os
paths=sorted(glob.glob('eval/results_revamp/single/eval_run.single_baseline_v1.*/score_summary.json'))
path=paths[-1]
print('score_summary_path',path)
print(json.dumps(json.load(open(path)),indent=2))
PY
