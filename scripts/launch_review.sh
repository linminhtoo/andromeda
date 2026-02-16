#!/bin/bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_env.sh"

export FINRAG_REVIEW_PORT="${FINRAG_REVIEW_PORT:-8237}"
export FINRAG_REVIEW_ROOTS="/home/mlin/repos/z_scratch/financial-rag/eval/results_v2"

script_dir="$(
  cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1
  pwd
)"
project_root="$(
  cd -- "$script_dir/.." >/dev/null 2>&1
  pwd
)"
cd "$project_root"

if ! command -v npm >/dev/null 2>&1; then
  echo "Missing npm; install Node.js/npm to build frontend TypeScript assets." >&2
  exit 1
fi

if [[ ! -f "$project_root/node_modules/typescript/package.json" ]]; then
  npm install --no-audit --no-fund
fi

npm run -s build:ts

source "$project_root/.venv/bin/activate"
PYTHONPATH=src uvicorn andromeda.review_app:app --host 0.0.0.0 --port "${FINRAG_REVIEW_PORT}"
