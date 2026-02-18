#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"

source .venv/bin/activate

python -m scripts.eval_dashboard \
  --runs-root eval/results_revamp/single \
  --runs-root eval/results_revamp/multi \
  --runs-root eval/results_revamp/openended \
  --runs-root eval/results_revamp/chunk_size_study_v2_expanded80k/runs \
  --runs-root eval/results_revamp/latency_accuracy_frontier_20260218/runs \
  --out-dir eval/results_revamp/dashboard_frontier_20260218 \
  --include-incomplete
