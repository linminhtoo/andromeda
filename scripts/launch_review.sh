#!/bin/bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_env.sh"

export FINRAG_REVIEW_PORT="${FINRAG_REVIEW_PORT:-8237}"
export FINRAG_REVIEW_ROOTS="/home/mlin/repos/z_scratch/financial-rag/eval/results_v2"

PYTHONPATH=src uvicorn finrag.review_app:app --host 0.0.0.0 --port "${FINRAG_REVIEW_PORT}"
