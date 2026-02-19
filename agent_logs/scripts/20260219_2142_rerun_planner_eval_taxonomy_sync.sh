#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."
source .venv/bin/activate

python -m scripts.make_planner_eval_set --out eval/eval_queries_planner_characteristics_manual100_20260219.jsonl
bash scripts/run_planner_eval_suite.sh
pytest tests/test_planner_eval_pipeline.py
