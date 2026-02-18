#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

source .venv/bin/activate
set -a; . ./.env; set +a

export POSTGRES_SCHEMA="eval_revamp_combined_512_20260217"
DOC_INDEX_PATH="data/ingest_profiles/eval_revamp_combined_512_20260217/sec_filings_md_secparser/chunked_512_64/doc_index.jsonl"
EVAL_QUERIES="eval/eval_queries_openended100_diverse_20260217_v1.jsonl"
OUT_DIR="eval/results_revamp/open"
RUN_NAME="open_diverse_iter4_narrativetemp0_normal_tools12_norefine_qt350_jt350"

python scripts/run_eval.py \
  --eval-queries "$EVAL_QUERIES" \
  --out-dir "$OUT_DIR" \
  --run-name "$RUN_NAME" \
  --mode normal \
  --concurrency 12 \
  --parallel-backend thread \
  --doc-index-path "$DOC_INDEX_PATH" \
  --query-timeout-s 350 \
  --query-max-retries 1 \
  --kinds open_ended

RUN_DIR="$(ls -td ${OUT_DIR}/eval_run.${RUN_NAME}.* | head -n 1)"

echo "RUN_DIR=${RUN_DIR}"

python scripts/score_eval.py \
  --run-dir "$RUN_DIR" \
  --kinds open_ended \
  --judge-workers 12 \
  --judge-context-chars 80000 \
  --judge-timeout-s 350 \
  --judge-max-retries 1

python - <<'PY'
import json
from pathlib import Path

out_root = Path('eval/results_revamp/open')
runs = sorted(out_root.glob('eval_run.open_diverse_iter4_narrativetemp0_normal_tools12_norefine_qt350_jt350.*'))
if not runs:
    raise SystemExit('No run directory found')
run = runs[-1]
summary = json.loads((run / 'score_summary.json').read_text(encoding='utf-8'))
print('run_dir', run)
print('open_ended_n_ok', summary.get('open_ended_n_ok'))
print('open_ended_judge_fail_rates', summary.get('open_ended_judge_fail_rates'))
PY
