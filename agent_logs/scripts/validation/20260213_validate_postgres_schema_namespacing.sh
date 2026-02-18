#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
source .venv/bin/activate

pre-commit run --all
pytest tests/ -q

python -m scripts.build_index --help >/tmp/build_index_help_20260213.txt

# Safety check: destructive flags on default schema must refuse before DB mutation.
python -m scripts.build_index \
  --ingest-output-dir ./data/sec_filings_md_secparser/chunked_1024_128 \
  --postgres-dsn postgresql://user:pass@127.0.0.1:6543/andromeda \
  --reset-corpus \
  --max-docs 0 \
  >/tmp/build_index_default_schema_guard_20260213.txt 2>&1 || true

grep -q "Refusing destructive operation on default schema" /tmp/build_index_default_schema_guard_20260213.txt
