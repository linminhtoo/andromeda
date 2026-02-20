#!/usr/bin/env bash
set -euo pipefail
source .venv/bin/activate
mkdir -p agent_logs/reports/retrieval_eval_20260218/lite_single_eval_probe
python - <<'PY'
from __future__ import annotations
import json
from pathlib import Path

query_id = '1dd6251b-e62b-4e58-ae52-35a1253e14c3'
src = Path('eval/results_revamp/full_suite/eval_run.reduced_heuristics_full_retry4_envoverride_20260218_195034.single100.normal.tools12.norefine.20260218_195034/eval_queries.jsonl')
out = Path('agent_logs/reports/retrieval_eval_20260218/lite_single_eval_probe/lite_single_query.jsonl')
line = None
with src.open('r', encoding='utf-8') as handle:
    for raw in handle:
        raw = raw.rstrip('\n')
        if not raw.strip():
            continue
        item = json.loads(raw)
        if item.get('id') == query_id:
            line = json.dumps(item, ensure_ascii=False)
            break
if line is None:
    raise SystemExit(f'Query id not found: {query_id}')
out.write_text(line + '\n', encoding='utf-8')
print(f'Wrote: {out}')
PY

python scripts/run_eval.py \
  --eval-queries agent_logs/reports/retrieval_eval_20260218/lite_single_eval_probe/lite_single_query.jsonl \
  --out-dir agent_logs/reports/retrieval_eval_20260218/lite_single_eval_probe \
  --run-name lite_isolated_timeout350 \
  --mode normal \
  --concurrency 1 \
  --parallel-backend thread \
  --query-timeout-s 350 \
  --query-max-retries 0
