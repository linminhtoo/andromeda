#!/usr/bin/env bash
set -euo pipefail

source .venv/bin/activate
set -a
. ./.env
set +a

RUN_IN="eval/results_revamp/open/eval_run.openended_chunk512_pool100_tools12_norefine.20260217_194234"
STAMP="$(date +%Y%m%d_%H%M%S)"
RUN_OUT="eval/results_revamp/open/eval_run.openended_chunk512_pool100_tools12_norefine_partial71_curated.${STAMP}"
export RUN_OUT

mkdir -p "$RUN_OUT"

python - <<'PY'
from __future__ import annotations

import json
import os
from pathlib import Path

run_in = Path("eval/results_revamp/open/eval_run.openended_chunk512_pool100_tools12_norefine.20260217_194234")
run_out = Path(os.environ["RUN_OUT"])

q_path = run_in / "eval_queries.jsonl"
g_path = run_in / "generations.jsonl"

if not q_path.exists() or not g_path.exists():
    raise SystemExit("missing input files")

rows_gen: list[dict] = []
query_order: list[str] = []
with g_path.open("r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        qid = str(obj.get("query_id") or "").strip()
        if not qid:
            continue
        rows_gen.append(obj)
        query_order.append(qid)

query_set = set(query_order)
rows_q_by_id: dict[str, dict] = {}
with q_path.open("r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        qid = str(obj.get("id") or "").strip()
        if qid and qid in query_set and qid not in rows_q_by_id:
            rows_q_by_id[qid] = obj

missing = [qid for qid in query_order if qid not in rows_q_by_id]
if missing:
    raise SystemExit(f"missing {len(missing)} query rows for generations")

rows_q = [rows_q_by_id[qid] for qid in query_order]

run_out.mkdir(parents=True, exist_ok=True)
with (run_out / "eval_queries.jsonl").open("w", encoding="utf-8") as f:
    for obj in rows_q:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")
with (run_out / "generations.jsonl").open("w", encoding="utf-8") as f:
    for obj in rows_gen:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")

print(f"Wrote {len(rows_q)} queries and {len(rows_gen)} generations to {run_out}")
PY

python scripts/score_eval.py \
  --run-dir "$RUN_OUT" \
  --judge-workers 8 \
  --judge-context-chars 80000 \
  --judge-timeout-s 300 \
  --judge-max-retries 1 \
  --kinds open_ended

printf "Curated/scored run: %s\n" "$RUN_OUT"
