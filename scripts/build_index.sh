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

# NOTE: Optional env flags:
#   POSTGRES_SCHEMA=exp_ctx_neighbors_w1_m24_ef200
#   POSTGRES_SPARSE_SEARCH_METHOD=bm25  # or fts
#   CONTEXT_MAX_TOKENS=256
#   DEBUG_SAMPLE_RATE=0.001
#   DEBUG_MAX_SAMPLES=5
#   DEBUG_SAMPLE_SEED=42
#   RESET_CORPUS=true
#   RECREATE_ANN_INDEX=true
#   ALLOW_DEFAULT_SCHEMA_MUTATIONS=true
ann_args=()
reset_args=()
schema_args=()
sparse_args=()
debug_args=()
safe_override_args=()
context_args=()
ingest_profile_args=()
if [[ -n "${ANN_HNSW_M:-}" ]]; then
  ann_args+=(--ann-hnsw-m "$ANN_HNSW_M")
fi
if [[ -n "${ANN_HNSW_EF_CONSTRUCTION:-}" ]]; then
  ann_args+=(--ann-hnsw-ef-construction "$ANN_HNSW_EF_CONSTRUCTION")
fi
if [[ -n "${POSTGRES_SCHEMA:-}" ]]; then
  schema_args+=(--postgres-schema "$POSTGRES_SCHEMA")
fi
if [[ -n "${POSTGRES_SPARSE_SEARCH_METHOD:-}" ]]; then
  sparse_args+=(--sparse-search-method "${POSTGRES_SPARSE_SEARCH_METHOD,,}")
fi
if [[ -n "${CONTEXT_MAX_TOKENS:-}" ]]; then
  context_args+=(--context-max-tokens "$CONTEXT_MAX_TOKENS")
fi
if [[ -n "${DEBUG_SAMPLE_RATE:-}" ]]; then
  debug_args+=(--debug-sample-rate "$DEBUG_SAMPLE_RATE")
fi
if [[ -n "${DEBUG_MAX_SAMPLES:-}" ]]; then
  debug_args+=(--debug-max-samples "$DEBUG_MAX_SAMPLES")
fi
if [[ -n "${DEBUG_SAMPLE_SEED:-}" ]]; then
  debug_args+=(--debug-sample-seed "$DEBUG_SAMPLE_SEED")
fi
if [[ "${RECREATE_ANN_INDEX:-0}" =~ ^(1|true|TRUE|yes|YES|on|ON)$ ]]; then
  ann_args+=(--recreate-ann-index)
fi
if [[ "${RESET_CORPUS:-0}" =~ ^(1|true|TRUE|yes|YES|on|ON)$ ]]; then
  reset_args+=(--reset-corpus)
fi
if [[ "${ALLOW_DEFAULT_SCHEMA_MUTATIONS:-0}" =~ ^(1|true|TRUE|yes|YES|on|ON)$ ]]; then
  safe_override_args+=(--allow-default-schema-mutations)
fi

ingest_profile_name="${FINRAG_INGEST_PROFILE:-${POSTGRES_SCHEMA:-default}}"
ingest_profile_args+=(--ingest-profile "$ingest_profile_name")

context_strategy="${CONTEXT_STRATEGY:-neighbors}"
context_window="${CONTEXT_WINDOW:-1}"
context_max_concurrency="${CONTEXT_MAX_CONCURRENCY:-64}"
index_batch_size="${INDEX_BATCH_SIZE:-256}"

# Safety guard for shared production DSNs.
if [[ ${#schema_args[@]} -eq 0 && ( ${#ann_args[@]} -gt 0 || ${#reset_args[@]} -gt 0 ) && ${#safe_override_args[@]} -eq 0 ]]; then
  echo "Refusing destructive/index-recreate run without POSTGRES_SCHEMA." >&2
  echo "Set POSTGRES_SCHEMA for experiment isolation, or ALLOW_DEFAULT_SCHEMA_MUTATIONS=true to override." >&2
  exit 1
fi

# INFO: 3 hours to index 93 documents with a total of 19389 chunks
# main cost comes from LLM-based contextualization of each chunk
# maybe context-window of 8 is too large.

# INFO: using window of 1 chunk before and after, with improved prompt + larger concurrent LLM requests: only 30 secs

# REMEMBER TO CHANGE --ingest-output-dir
# NOTE: set --skip-existing-chunks if desired
python3 -m scripts.build_index \
  --ingest-output-dir ./data/sec_filings_md_secparser/chunked_1024_128 \
  --postgres-dsn "${POSTGRES_DSN:-${DATABASE_URL:-}}" \
  --llm-provider openai \
  --dense-model BAAI/bge-m3 \
  --dense-base-url "${OPENAI_EMBED_BASE_URL:-}" \
  --contextual-llm-provider openai \
  --contextual-model "Qwen/Qwen3-VL-32B-Instruct-FP8" \
  --contextual-base-url "${OPENAI_CONTEXT_BASE_URL:-}" \
  --context "$context_strategy" \
  --context-window "$context_window" \
  --context-max-concurrency "$context_max_concurrency" \
  --batch-size "$index_batch_size" \
  "${ingest_profile_args[@]}" \
  "${context_args[@]}" \
  "${schema_args[@]}" \
  "${sparse_args[@]}" \
  "${debug_args[@]}" \
  "${reset_args[@]}" \
  "${ann_args[@]}" \
  "${safe_override_args[@]}" \
  2>&1 | tee "logs/build_index_${now}.log"
