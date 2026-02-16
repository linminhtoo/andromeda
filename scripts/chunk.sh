#!/bin/bash
set -euo pipefail

# NOTE: script does logging setup internally.
source "$(dirname "${BASH_SOURCE[0]}")/_env.sh"

script_dir="$(
  cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1
  pwd
)"
project_root="$(
  cd -- "$script_dir/.." >/dev/null 2>&1
  pwd
)"
cd "$project_root"

chunk_max_tokens="${CHUNK_MAX_TOKENS:-1024}"
chunk_overlap_tokens="${CHUNK_OVERLAP_TOKENS:-128}"
chunker_name="${CHUNKER_NAME:-markdown_table_preserving}"
ingest_profile_name="${FINRAG_INGEST_PROFILE:-${POSTGRES_SCHEMA:-default}}"
markdown_root="${SEC_FILINGS_MD_ROOT:-${project_root}/data/ingest_profiles/${ingest_profile_name}/sec_filings_md_secparser}"
chunk_output_dir="${CHUNK_OUTPUT_DIR:-${markdown_root}/chunked_${chunk_max_tokens}_${chunk_overlap_tokens}}"

# runs almost instantaneously
# with MiniLM tokenizer, it is not instant, about 35 secs for 93 documents, still very fast.
python3 -m scripts.chunk \
  --markdown-dir "${markdown_root}/processed_markdown" \
  --metadata-dir "${markdown_root}/debug" \
  --output-dir "$chunk_output_dir" \
  --ingest-profile "$ingest_profile_name" \
  --chunker "$chunker_name" \
  --max-tokens "$chunk_max_tokens" \
  --overlap-tokens "$chunk_overlap_tokens" \
  --overwrite \
  --recursive
