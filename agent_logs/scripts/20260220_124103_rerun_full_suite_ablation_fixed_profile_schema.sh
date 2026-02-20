#!/usr/bin/env bash
set -euo pipefail

source .venv/bin/activate

INGEST_PROFILE="eval_revamp_combined_512_20260217" \
CHUNK_DIR="chunked_512_64" \
POSTGRES_SCHEMA="eval_revamp_combined_512_20260217" \
RUN_GROUP="full_suite_ablation_fixed_20260220_124103" \
bash agent_logs/scripts/20260219_2358_run_full_suite_rerank_material_ablation.sh
