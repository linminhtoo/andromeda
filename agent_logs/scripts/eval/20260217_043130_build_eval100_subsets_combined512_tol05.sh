#!/usr/bin/env bash
set -euo pipefail

cd /home/mlin/repos/z_scratch/financial-rag
source .venv/bin/activate

python - <<'PY'
import json
import random
import re
from collections import Counter
from pathlib import Path

src = Path('eval/eval_queries_combined512_validated_tol05_20260217.jsonl')
rows = [json.loads(line) for line in src.read_text(encoding='utf-8').splitlines() if line.strip()]

factual_matched: list[dict] = []
factual_other: list[dict] = []
open_ended: list[dict] = []
refusal: list[dict] = []
distractor: list[dict] = []
comparison: list[dict] = []

for row in rows:
    kind = row['kind']
    if kind == 'factual':
        status = ((row.get('generator') or {}).get('edgar_validation') or {}).get('status', 'missing')
        if status == 'matched':
            factual_matched.append(row)
        else:
            factual_other.append(row)
    elif kind == 'open_ended':
        open_ended.append(row)
    elif kind == 'refusal':
        refusal.append(row)
    elif kind == 'distractor':
        distractor.append(row)
    elif kind == 'comparison':
        comparison.append(row)

rng = random.Random(20260217)
for bucket in (factual_matched, factual_other, open_ended, refusal, distractor, comparison):
    rng.shuffle(bucket)

GENERIC_TAGS = {
    'FACTUAL', 'SEC', 'OPEN_ENDED', 'REFUSAL', 'DISTRACTOR', 'COMPARISON', '10-Q', '10-K',
    'PROMPT_INJECTION', 'UNKNOWN_COMPANY', 'NON_INVESTMENT',
}
TICKER_RE = re.compile(r"\(([A-Z][A-Z0-9.-]{0,10})\)")


def row_tickers(row: dict) -> list[str]:
    kind = row['kind']
    if kind == 'comparison':
        tickers = ((row.get('comparison') or {}).get('target_tickers') or [])
        return [str(t).strip().upper() for t in tickers if str(t).strip()]
    if kind == 'distractor':
        tickers = ((row.get('distractor') or {}).get('target_tickers') or [])
        if tickers:
            return [str(t).strip().upper() for t in tickers if str(t).strip()]
    if kind == 'open_ended':
        ticker = ((row.get('open_ended') or {}).get('target_ticker') or '').strip().upper()
        if ticker:
            return [ticker]
    if kind == 'refusal':
        ticker = ((row.get('refusal') or {}).get('target_ticker') or '').strip().upper()
        if ticker:
            return [ticker]

    for tag in row.get('tags') or []:
        token = str(tag).strip().upper()
        if not token or token in GENERIC_TAGS:
            continue
        if re.fullmatch(r"[A-Z][A-Z0-9.-]{0,10}", token):
            return [token]

    q = str(row.get('question') or '')
    m = TICKER_RE.search(q)
    if m:
        return [m.group(1).strip().upper()]
    return []


def sample_with_coverage(rows: list[dict], n: int) -> list[dict]:
    selected: list[dict] = []
    used_ids: set[str] = set()
    seen_tickers: set[str] = set()

    for row in rows:
        if len(selected) >= n:
            break
        row_id = str(row.get('id') or '')
        if row_id in used_ids:
            continue
        tickers = set(row_tickers(row))
        if tickers and (tickers - seen_tickers):
            selected.append(row)
            used_ids.add(row_id)
            seen_tickers.update(tickers)

    for row in rows:
        if len(selected) >= n:
            break
        row_id = str(row.get('id') or '')
        if row_id in used_ids:
            continue
        selected.append(row)
        used_ids.add(row_id)
        seen_tickers.update(row_tickers(row))

    return selected[:n]

single_counts = {'factual': 35, 'open_ended': 30, 'refusal': 20, 'distractor': 15}

factual_rows = sample_with_coverage(factual_matched, single_counts['factual'])
if len(factual_rows) < single_counts['factual']:
    need = single_counts['factual'] - len(factual_rows)
    factual_rows.extend(sample_with_coverage(factual_other, need))

single_rows: list[dict] = []
single_rows.extend(factual_rows)
single_rows.extend(sample_with_coverage(open_ended, single_counts['open_ended']))
single_rows.extend(sample_with_coverage(refusal, single_counts['refusal']))
single_rows.extend(sample_with_coverage(distractor, single_counts['distractor']))
rng.shuffle(single_rows)

multi_rows = sample_with_coverage(comparison, 60)

single_out = Path('eval/eval_queries_combined512_single_balanced100_validated_tol05_20260217.jsonl')
multi_out = Path('eval/eval_queries_combined512_multi_comparison60_validated_tol05_20260217.jsonl')

single_out.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in single_rows), encoding='utf-8')
multi_out.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in multi_rows), encoding='utf-8')

single_kind = Counter(row['kind'] for row in single_rows)
single_factual_statuses = Counter(
    ((row.get('generator') or {}).get('edgar_validation') or {}).get('status', 'missing')
    for row in single_rows
    if row['kind'] == 'factual'
)
single_tickers = Counter(t for row in single_rows for t in row_tickers(row))

print('single_out', single_out, 'n=', len(single_rows))
print('single_kind', dict(single_kind))
print('single_factual_statuses', dict(single_factual_statuses))
print('single_unique_tickers', len(single_tickers), sorted(single_tickers.keys()))
print('multi_out', multi_out, 'n=', len(multi_rows))
PY
