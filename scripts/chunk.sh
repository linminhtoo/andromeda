#!/bin/bash
set -euo pipefail

# NOTE: script does logging setup internally.
source "$(dirname "${BASH_SOURCE[0]}")/_env.sh"

# runs almost instantaneously
python3 -m scripts.chunk \
  --markdown-dir /home/mlin/repos/z_scratch/financial-rag/data/sec_filings_md_secparser/processed_markdown \
  --metadata-dir /home/mlin/repos/z_scratch/financial-rag/data/sec_filings_md_secparser/debug \
  --output-dir /home/mlin/repos/z_scratch/financial-rag/data/sec_filings_md_secparser/chunked_1024_128 \
  --chunker markdown_table_preserving \
  --max-tokens 1024 \
  --overlap-tokens 128 \
  --recursive
