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

# Optional model overrides for local OpenAI-compatible endpoints.
: "${OPENAI_CHAT_MODEL:=Qwen/Qwen3-VL-32B-Instruct-FP8}"
: "${OPENAI_EMBED_MODEL:=BAAI/bge-m3}"
: "${RERANKER_MODEL:=BAAI/bge-reranker-v2-m3}"

export OPENAI_CHAT_MODEL OPENAI_EMBED_MODEL RERANKER_MODEL
export CONTEXT_STRATEGY="${CONTEXT_STRATEGY:-neighbors}"
export CONTEXT_WINDOW="${CONTEXT_WINDOW:-8}"

source "$project_root/.venv/bin/activate"
PYTHONPATH=src uvicorn finrag.main:app --host 0.0.0.0 --port 8236
