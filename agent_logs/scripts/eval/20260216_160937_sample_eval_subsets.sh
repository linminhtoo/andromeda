#!/usr/bin/env bash
set -euo pipefail

cd /home/mlin/repos/z_scratch/financial-rag
source .venv/bin/activate

python3 - <<'PY'
import json, random
from pathlib import Path

src = Path('eval/eval_queries_revamp_20260216.jsonl')
rows = [json.loads(line) for line in src.read_text(encoding='utf-8').splitlines() if line.strip()]

single_by_kind = {k: [] for k in ('factual','open_ended','refusal','distractor')}
comparison = []
for row in rows:
    kind = row['kind']
    if kind == 'comparison':
        comparison.append(row)
        continue
    if kind in single_by_kind:
        single_by_kind[kind].append(row)

rng = random.Random(20260216)
for lst in single_by_kind.values():
    rng.shuffle(lst)
rng.shuffle(comparison)

single_counts = {'factual': 30, 'open_ended': 25, 'refusal': 10, 'distractor': 10}
single_rows = []
for kind, n in single_counts.items():
    single_rows.extend(single_by_kind[kind][:n])
rng.shuffle(single_rows)

multi_rows = comparison[:32]

single_out = Path('eval/eval_queries_revamp_single_balanced_20260216.jsonl')
multi_out = Path('eval/eval_queries_revamp_multi_comparison_20260216.jsonl')

single_out.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in single_rows), encoding='utf-8')
multi_out.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in multi_rows), encoding='utf-8')

print('single_out', single_out, 'n=', len(single_rows))
print('multi_out', multi_out, 'n=', len(multi_rows))
PY
