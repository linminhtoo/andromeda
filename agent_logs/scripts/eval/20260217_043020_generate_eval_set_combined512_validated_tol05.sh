#!/usr/bin/env bash
set -euo pipefail

cd /home/mlin/repos/z_scratch/financial-rag
source .venv/bin/activate
set -a
. ./.env
set +a

export HOME=/tmp

INGEST_DIR="data/ingest_profiles/eval_revamp_combined_512_20260217/sec_filings_md_secparser/chunked_512_64"
OUT_PATH="eval/eval_queries_combined512_validated_tol05_20260217.jsonl"

python -m scripts.make_eval_set \
  --ingest-output-dir "${INGEST_DIR}" \
  --out "${OUT_PATH}" \
  --max-docs 400 \
  --max-chunks-per-doc 220 \
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

path='eval/eval_queries_combined512_validated_tol05_20260217.jsonl'
kind=Counter(); status=Counter(); tick=Counter()
for line in open(path, encoding='utf-8'):
    r=json.loads(line)
    kind[r['kind']]+=1
    if r['kind']!='factual':
        continue
    s=((r.get('generator') or {}).get('edgar_validation') or {}).get('status','missing')
    status[s]+=1
    for tag in (r.get('tags') or []):
        tt=str(tag).strip().upper()
        if tt and tt.isalnum() and tt not in {'FACTUAL','SEC','10-Q','10-K'}:
            tick[tt]+=1
            break
print('path', path)
print('total', sum(kind.values()))
print('kinds', dict(kind))
print('factual_edgar_statuses', dict(status))
print('factual_top_tickers', tick.most_common(20))
PY
