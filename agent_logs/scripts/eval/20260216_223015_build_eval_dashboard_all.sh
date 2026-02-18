#!/usr/bin/env bash
set -euo pipefail

cd /home/mlin/repos/z_scratch/financial-rag
source .venv/bin/activate

python3 -m scripts.eval_dashboard \
  --runs-root eval/results_revamp/single \
  --runs-root eval/results_revamp/multi \
  --out-dir eval/results_revamp/dashboard \
  --include-incomplete
