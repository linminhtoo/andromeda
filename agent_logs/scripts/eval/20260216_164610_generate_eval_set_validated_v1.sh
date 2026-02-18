#!/usr/bin/env bash
set -euo pipefail

cd /home/mlin/repos/z_scratch/financial-rag
source .venv/bin/activate
set -a
. ./.env
set +a

INGEST_DIR="data/ingest_profiles/eval_revamp_20260216/sec_filings_md_secparser/chunked_1024_128"
OUT_PATH="eval/eval_queries_revamp_validated_20260216.jsonl"

python3 -m scripts.make_eval_set \
  --ingest-output-dir "${INGEST_DIR}" \
  --out "${OUT_PATH}" \
  --max-docs 200 \
  --max-chunks-per-doc 160 \
  --n-factual 80 \
  --n-open-ended 60 \
  --n-refusal 24 \
  --n-distractor 24 \
  --n-comparison 40 \
  --seed 1602 \
  --snippet-chars 5000 \
  --validate-factual-with-edgar \
  --edgar-drop-mismatched \
  --edgar-rel-tol 0.2 \
  --factual-candidate-multiplier 8

python3 - <<'PY'
import json
from collections import Counter

path='eval/eval_queries_revamp_validated_20260216.jsonl'
kind=Counter()
statuses=Counter()
for line in open(path, encoding='utf-8'):
    row=json.loads(line)
    kind[row['kind']]+=1
    if row['kind']!='factual':
        continue
    status=((row.get('generator') or {}).get('edgar_validation') or {}).get('status','missing')
    statuses[status]+=1
print('path', path)
print('total', sum(kind.values()))
print('kinds', dict(kind))
print('factual_edgar_statuses', dict(statuses))
PY
