#!/usr/bin/env bash
set -euo pipefail

cd /home/mlin/repos/z_scratch/financial-rag
source .venv/bin/activate

python3 - <<'PY'
import json
import random
from collections import Counter
from pathlib import Path

src = Path('eval/eval_queries_revamp_validated_tol05_20260216.jsonl')
rows = [json.loads(line) for line in src.read_text(encoding='utf-8').splitlines() if line.strip()]

factual_matched = []
factual_other = []
open_ended = []
refusal = []
distractor = []
comparison = []

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

rng = random.Random(20260216)
for bucket in (factual_matched, factual_other, open_ended, refusal, distractor, comparison):
    rng.shuffle(bucket)

single_counts = {'factual': 20, 'open_ended': 15, 'refusal': 8, 'distractor': 7}
factual_rows = factual_matched[: single_counts['factual']]
if len(factual_rows) < single_counts['factual']:
    need = single_counts['factual'] - len(factual_rows)
    factual_rows.extend(factual_other[:need])

single_rows = []
single_rows.extend(factual_rows)
single_rows.extend(open_ended[: single_counts['open_ended']])
single_rows.extend(refusal[: single_counts['refusal']])
single_rows.extend(distractor[: single_counts['distractor']])
rng.shuffle(single_rows)

multi_rows = comparison[:24]

single_out = Path('eval/eval_queries_revamp_single_balanced_validated_tol05_20260216.jsonl')
multi_out = Path('eval/eval_queries_revamp_multi_comparison_validated_tol05_20260216.jsonl')

single_out.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in single_rows), encoding='utf-8')
multi_out.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in multi_rows), encoding='utf-8')

factual_statuses = Counter(((row.get('generator') or {}).get('edgar_validation') or {}).get('status', 'missing') for row in factual_rows)
print('single_out', single_out, 'n=', len(single_rows))
print('single_factual_statuses', dict(factual_statuses))
print('multi_out', multi_out, 'n=', len(multi_rows))
PY
