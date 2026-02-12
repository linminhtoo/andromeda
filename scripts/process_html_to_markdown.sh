#!/bin/bash
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/_env.sh"
export LOGLEVEL=DEBUG

mkdir -p logs/
now=$(date +"%Y%m%d_%H%M%S")

# much faster than `marker` OCR pipeline, 1 sec per file instead of 10 mins per file
# no LLM involved, pure parsing of HTML elements
# much less error prone as well
python3 -m scripts.process_html_to_markdown \
  --html-dir "./data/sec_filings/raw_htmls/" \
  --meta-dir "./data/sec_filings/meta/" \
  --output-dir "./data/sec_filings_md_secparser/" \
  --recursive \
  --year-cutoff 2023 \
  --parser-mode auto \
  --continue-on-error \
  2>&1 | tee "logs/process_sec_parser_${now}.log"
