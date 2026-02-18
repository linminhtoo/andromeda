#!/usr/bin/env bash
set -euo pipefail

cd /home/mlin/repos/z_scratch/financial-rag
source .venv/bin/activate

INGEST_DIR="data/ingest_profiles/eval_revamp_20260216/sec_filings_md_secparser/chunked_1024_128"
OUT_PATH="eval/eval_queries_revamp_20260216.jsonl"

python3 -m scripts.make_eval_set \
  --ingest-output-dir "${INGEST_DIR}" \
  --out "${OUT_PATH}" \
  --max-docs 200 \
  --max-chunks-per-doc 160 \
  --n-factual 60 \
  --n-open-ended 60 \
  --n-refusal 24 \
  --n-distractor 24 \
  --n-comparison 40 \
  --seed 16 \
  --snippet-chars 5000

python3 - <<'PY'
import json
from collections import Counter
path='eval/eval_queries_revamp_20260216.jsonl'
kind=Counter(); multi=0; n=0
for line in open(path,encoding='utf-8'):
    row=json.loads(line); n+=1
    kind[row['kind']]+=1
    if row.get('comparison') and len(set((row['comparison'].get('target_tickers') or [])))>1:
        multi+=1
    if row.get('distractor') and len(set((row['distractor'].get('target_tickers') or [])))>1:
        multi+=1
print('total',n)
print('kinds',dict(kind))
print('multi_like',multi)
PY
