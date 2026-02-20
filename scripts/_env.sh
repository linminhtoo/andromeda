#!/usr/bin/env bash
set -euo pipefail

# Loads env vars from the project root `.env` file (if present) and exports them.
# Usage: source "$(dirname "${BASH_SOURCE[0]}")/_env.sh"

script_dir="$(
  cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1
  pwd
)"
project_root="$(
  cd -- "$script_dir/.." >/dev/null 2>&1
  pwd
)"

env_file="${ENV_FILE:-$project_root/.env}"
if [[ -f "$env_file" ]]; then
  set -a
  # shellcheck source=/dev/null
  . "$env_file"
  set +a
else
  echo "Warning: .env not found at: $env_file (copy .env.example -> .env)" >&2
fi

# Resolve a doc_index path for eval scripts while avoiding silent drift from stale
# `.env` values. We intentionally do not treat FINRAG_DOC_INDEX_PATH as a default
# source in eval scripts; pass DOC_INDEX_PATH (or FINRAG_DOC_INDEX_PATH_OVERRIDE)
# explicitly for one-off overrides.
resolve_eval_doc_index_path() {
  local root="$1"
  local ingest_profile="$2"
  local chunk_dir="$3"

  local inferred="${root}/data/ingest_profiles/${ingest_profile}/sec_filings_md_secparser/${chunk_dir}/doc_index.jsonl"
  local explicit="${DOC_INDEX_PATH:-${FINRAG_DOC_INDEX_PATH_OVERRIDE:-}}"
  local legacy="${FINRAG_DOC_INDEX_PATH:-}"
  local resolved="$inferred"

  if [[ -n "$explicit" ]]; then
    resolved="$explicit"
  elif [[ -n "$legacy" && "$legacy" != "$inferred" ]]; then
    echo "Warning: ignoring FINRAG_DOC_INDEX_PATH from .env for eval script resolution." >&2
    echo "         inferred=${inferred}" >&2
    echo "         legacy=${legacy}" >&2
    echo "         Use DOC_INDEX_PATH (or FINRAG_DOC_INDEX_PATH_OVERRIDE) to override intentionally." >&2
  fi

  if [[ "$resolved" != /* ]]; then
    resolved="${root}/${resolved#./}"
  fi
  echo "$resolved"
}
