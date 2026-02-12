#!/bin/bash
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/_env.sh"

if [[ -z "${POSTGRES_DSN:-${DATABASE_URL:-}}" ]]; then
  echo "Missing POSTGRES_DSN (or DATABASE_URL)." >&2
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

python3 -m scripts.inspect_collection \
  --postgres-dsn "${POSTGRES_DSN:-${DATABASE_URL:-}}" \
  --max-chars 0 \
  --json \
  --limit 10 \
  2>&1 | tee "logs/inspect_collection_${now}.log"
