#!/bin/bash
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/_env.sh"
export LOGLEVEL=DEBUG

script_dir="$(
  cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1
  pwd
)"
project_root="$(
  cd -- "$script_dir/.." >/dev/null 2>&1
  pwd
)"
cd "$project_root"

mkdir -p logs/
now=$(date +"%Y%m%d_%H%M%S")
ingest_profile_name="${FINRAG_INGEST_PROFILE:-${POSTGRES_SCHEMA:-default}}"
sec_filings_root="${SEC_FILINGS_ROOT:-${project_root}/data/ingest_profiles/${ingest_profile_name}/sec_filings}"
markdown_root="${SEC_FILINGS_MD_ROOT:-${project_root}/data/ingest_profiles/${ingest_profile_name}/sec_filings_md_secparser}"

# much faster than `marker` OCR pipeline, 1 sec per file instead of 10 mins per file
# no LLM involved, pure parsing of HTML elements
# much less error prone as well
python3 -m scripts.process_html_to_markdown \
  --html-dir "${sec_filings_root}/raw_htmls/" \
  --meta-dir "${sec_filings_root}/meta/" \
  --output-dir "${markdown_root}/" \
  --ingest-profile "$ingest_profile_name" \
  --recursive \
  --year-cutoff 2025 \
  --parser-mode auto \
  --continue-on-error \
  2>&1 | tee "logs/process_sec_parser_${now}.log"
