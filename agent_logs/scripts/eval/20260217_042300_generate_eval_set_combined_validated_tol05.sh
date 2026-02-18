#!/usr/bin/env bash
set -euo pipefail

cd /home/mlin/repos/z_scratch/financial-rag
source .venv/bin/activate
set -a
. ./.env
set +a

export HOME=/tmp

INGEST_DIR="data/ingest_profiles/eval_revamp_combined_20260217/sec_filings_md_secparser/chunked_1024_128"
OUT_PATH="eval/eval_queries_combined_validated_tol05_20260217.jsonl"

python -m scripts.make_eval_set \
  --ingest-output-dir "${INGEST_DIR}" \
  --out "${OUT_PATH}" \
  --max-docs 400 \
  --max-chunks-per-doc 180 \
  --n-factual 220 \
  --n-open-ended 100 \
  --n-refusal 50 \
  --n-distractor 50 \
  --n-comparison 70 \
  --seed 20260217 \
  --snippet-chars 5000 \
  --validate-factual-with-edgar \
  --edgar-rel-tol 0.5 \
  --factual-candidate-multiplier 8

python - <<'PY'
import json
from collections import Counter

path='eval/eval_queries_combined_validated_tol05_20260217.jsonl'
kind=Counter()
statuses=Counter()
factual_tickers=Counter()

for line in open(path, encoding='utf-8'):
    row=json.loads(line)
    kind[row['kind']]+=1
    if row['kind']=='factual':
        status=((row.get('generator') or {}).get('edgar_validation') or {}).get('status','missing')
        statuses[status]+=1
        doc_id = ((row.get('factual') or {}).get('golden_evidence') or {}).get('doc_id') or ''
        ticker = str(doc_id).split('_',1)[0].upper() if doc_id else ''
        if ticker:
            factual_tickers[ticker]+=1

print('path', path)
print('total', sum(kind.values()))
print('kinds', dict(kind))
print('factual_edgar_statuses', dict(statuses))
print('factual_top_tickers', factual_tickers.most_common(20))
PY
