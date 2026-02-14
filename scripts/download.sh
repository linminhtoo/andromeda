#!/bin/bash
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/_env.sh"

now=$(date +%Y%m%d_%H%M%S)
python3 scripts/download.py \
	--tickers "APH" "GOOGL" "NVDA" "AMD" "TER" "LITE" \
				"SNDK" "MU" \
	--output-dir ./data/sec_filings/ \
	--per-company 10 \
	--skip-existing \
	2>&1 | tee logs/download_${now}.log
