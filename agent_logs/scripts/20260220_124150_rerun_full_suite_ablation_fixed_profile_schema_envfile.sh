#!/usr/bin/env bash
set -euo pipefail

source .venv/bin/activate

tmp_env="$(mktemp /tmp/finrag_eval_env_XXXXXX.env)"
trap 'rm -f "$tmp_env"' EXIT

grep -v '^POSTGRES_SCHEMA=' .env | grep -v '^FINRAG_DOC_INDEX_PATH=' > "$tmp_env"
cat >> "$tmp_env" <<'ENVVARS'
POSTGRES_SCHEMA=eval_revamp_combined_512_20260217
FINRAG_INGEST_PROFILE=eval_revamp_combined_512_20260217
ENVVARS

ENV_FILE="$tmp_env" \
INGEST_PROFILE="eval_revamp_combined_512_20260217" \
CHUNK_DIR="chunked_512_64" \
RUN_GROUP="full_suite_ablation_fixed_20260220_124150" \
bash agent_logs/scripts/20260219_2358_run_full_suite_rerank_material_ablation.sh
