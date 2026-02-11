#!/bin/bash
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/_env.sh"

if [[ -z "${POSTGRES_DSN:-${DATABASE_URL:-}}" ]]; then
  echo "Missing POSTGRES_DSN (or DATABASE_URL)." >&2
  exit 1
fi

if [[ -z "${FINRAG_DOC_INDEX_PATH:-}" ]]; then
  echo "Set FINRAG_DOC_INDEX_PATH in .env (or pass --doc-index-path)." >&2
  exit 1
fi

script_dir="$(
  cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1
  pwd
)"
project_root="$(
  cd -- "$script_dir/.." >/dev/null 2>&1
  pwd
)"
cd "$project_root"

now=$(date +"%Y%m%d_%H%M%S")
mkdir -p logs

python3 -m scripts.run_eval \
  --eval-queries ./eval/eval_queries_v2.jsonl \
  --out-dir ./eval/results_v2/${now} \
  --run-name postgres_baseline_v1 \
  --mode thinking \
  --concurrency 8 \
  --gpu-ids 0 1 \
  2>&1 | tee logs/run_eval_${now}.log
