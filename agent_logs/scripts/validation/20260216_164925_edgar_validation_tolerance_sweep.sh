#!/usr/bin/env bash
set -euo pipefail

cd /home/mlin/repos/z_scratch/financial-rag
source .venv/bin/activate
set -a
. ./.env
set +a

export HOME=/tmp

python3 - <<'PY'
from collections import Counter

from andromeda.eval.generation import generate_factual_queries
from andromeda.eval.ground_truth_validation import validate_factual_queries_with_edgar
from andromeda.eval.sec_corpus import iter_all_chunks

chunks = iter_all_chunks(
    'data/ingest_profiles/eval_revamp_20260216/sec_filings_md_secparser/chunked_1024_128',
    tickers=None,
    forms=None,
    max_docs=200,
    max_chunks_per_doc=160,
)

factual = generate_factual_queries(chunks, n=640, seed=1602, snippet_chars=5000)
print('candidate_factual', len(factual))
for tol in (0.15, 0.2, 0.25, 0.3, 0.4, 0.5):
    kept, stats = validate_factual_queries_with_edgar(factual, rel_tol=tol, drop_mismatched=False)
    statuses = Counter()
    for q in kept:
        if q.kind != 'factual':
            continue
        status = ((q.generator or {}).get('edgar_validation') or {}).get('status', 'missing')
        statuses[status] += 1
    print('tol', tol, 'stats', stats.to_dict(), 'status_counts', dict(statuses))
PY
