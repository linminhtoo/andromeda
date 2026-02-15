#!/bin/bash
set -euo pipefail

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

now=$(date +%Y%m%d_%H%M%S)
ingest_profile_name="${FINRAG_INGEST_PROFILE:-${POSTGRES_SCHEMA:-default}}"
download_output_dir="${DOWNLOAD_OUTPUT_DIR:-${project_root}/data/ingest_profiles/${ingest_profile_name}/sec_filings}"

python3 scripts/download.py \
	--tickers "APH" "GOOGL" "NVDA" "AMD" "TER" "LITE" \
				"SNDK" "MU" "INTC" \
				"CENX" "CAT" "IESC" "FIX" "GEV" "ATI" \
	--output-dir "$download_output_dir" \
	--ingest-profile "$ingest_profile_name" \
	--skip-existing \
	--year-cutoff 2025 \
	2>&1 | tee logs/download_${now}.log
