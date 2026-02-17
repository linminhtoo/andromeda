#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

source .venv/bin/activate
set -a; . ./.env; set +a

INGEST_DIR="data/ingest_profiles/eval_revamp_combined_512_20260217/sec_filings_md_secparser/chunked_512_64"
OUT_JSONL="eval/eval_queries_openended200_diverse_20260217_v1.jsonl"
SEED="20260217"

python scripts/make_eval_set.py \
  --ingest-output-dir "$INGEST_DIR" \
  --out "$OUT_JSONL" \
  --max-docs 450 \
  --max-chunks-per-doc 180 \
  --n-factual 0 \
  --n-open-ended 200 \
  --n-refusal 0 \
  --n-distractor 0 \
  --n-comparison 0 \
  --seed "$SEED"

python - <<'PY'
import json
from collections import Counter
from pathlib import Path

path = Path('eval/eval_queries_openended200_diverse_20260217_v1.jsonl')
rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
print('rows', len(rows))
kind_counts = Counter(r.get('kind') for r in rows)
print('kind_counts', dict(kind_counts))
family_counts = Counter()
ticker_counts = Counter()
year_counts = Counter()
for row in rows:
    gen = row.get('generator') or {}
    family = gen.get('template_family')
    if isinstance(family, str) and family:
        family_counts[family] += 1
    oe = row.get('open_ended') or {}
    ticker = oe.get('target_ticker')
    year = oe.get('target_year')
    if isinstance(ticker, str) and ticker:
        ticker_counts[ticker] += 1
    if isinstance(year, int):
        year_counts[year] += 1
print('family_count_n', len(family_counts))
print('family_counts', dict(sorted(family_counts.items())))
print('ticker_count_n', len(ticker_counts))
print('top_tickers', ticker_counts.most_common(20))
print('year_count_n', len(year_counts))
print('year_counts', dict(sorted(year_counts.items())))
PY
