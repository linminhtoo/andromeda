#!/usr/bin/env bash
set -euo pipefail

repo_root="$(
  cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." >/dev/null 2>&1
  pwd
)"
cd "$repo_root"

source .venv/bin/activate

python -m scripts.make_planner_eval_set \
  --out eval/eval_queries_planner_characteristics_manual100_20260219.jsonl
