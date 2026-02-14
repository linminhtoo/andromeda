#!/bin/bash
set -euo pipefail

# NOTE: script does logging setup internally.
source "$(dirname "${BASH_SOURCE[0]}")/_env.sh"

chunk_max_tokens="${CHUNK_MAX_TOKENS:-1024}"
chunk_overlap_tokens="${CHUNK_OVERLAP_TOKENS:-128}"
chunker_name="${CHUNKER_NAME:-markdown_table_preserving}"
chunk_output_dir="${CHUNK_OUTPUT_DIR:-/home/mlin/repos/z_scratch/financial-rag/data/sec_filings_md_secparser/chunked_${chunk_max_tokens}_${chunk_overlap_tokens}}"
ingest_profile_name="${FINRAG_INGEST_PROFILE:-${POSTGRES_SCHEMA:-default}}"

# runs almost instantaneously
python3 -m scripts.chunk \
  --markdown-dir /home/mlin/repos/z_scratch/financial-rag/data/sec_filings_md_secparser/processed_markdown \
  --metadata-dir /home/mlin/repos/z_scratch/financial-rag/data/sec_filings_md_secparser/debug \
  --output-dir "$chunk_output_dir" \
  --ingest-profile "$ingest_profile_name" \
  --chunker "$chunker_name" \
  --max-tokens "$chunk_max_tokens" \
  --overlap-tokens "$chunk_overlap_tokens" \
  --recursive
