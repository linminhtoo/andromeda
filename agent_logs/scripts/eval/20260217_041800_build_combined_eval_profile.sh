#!/usr/bin/env bash
set -euo pipefail

cd /home/mlin/repos/z_scratch/financial-rag
source .venv/bin/activate
set -a
. ./.env
set +a

export HOME=/tmp

PROFILE="eval_revamp_combined_20260217"
SCHEMA="${PROFILE}"
TARGET_CHUNK_DIR="data/ingest_profiles/${PROFILE}/sec_filings_md_secparser/chunked_1024_128"
TARGET_CHUNKS="${TARGET_CHUNK_DIR}/chunks"

SRC_A="data/ingest_profiles/eval_revamp_20260216/sec_filings_md_secparser/chunked_1024_128"
SRC_B="data/ingest_profiles/exp__chunk_1024_o128_tokenizer__ctx_none__index_m24_ef200/sec_filings_md_secparser/chunked_1024_128"

mkdir -p "${TARGET_CHUNKS}"

rsync -a --ignore-existing "${SRC_A}/chunks/" "${TARGET_CHUNKS}/"
rsync -a --ignore-existing "${SRC_B}/chunks/" "${TARGET_CHUNKS}/"

python - <<'PY'
import json
from collections import Counter
from pathlib import Path

src_a = Path('data/ingest_profiles/eval_revamp_20260216/sec_filings_md_secparser/chunked_1024_128/doc_index.jsonl')
src_b = Path('data/ingest_profiles/exp__chunk_1024_o128_tokenizer__ctx_none__index_m24_ef200/sec_filings_md_secparser/chunked_1024_128/doc_index.jsonl')
out = Path('data/ingest_profiles/eval_revamp_combined_20260217/sec_filings_md_secparser/chunked_1024_128/doc_index.jsonl')
out.parent.mkdir(parents=True, exist_ok=True)

by_doc_id: dict[str, dict] = {}
for path in (src_a, src_b):
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        doc_id = str(row.get('doc_id') or '').strip()
        if not doc_id:
            continue
        by_doc_id.setdefault(doc_id, row)

rows = sorted(by_doc_id.values(), key=lambda r: str(r.get('doc_id') or ''))
out.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')

ticker_counter = Counter()
for r in rows:
    md = r.get('metadata') or {}
    ticker = str((md.get('doc') or {}).get('ticker') or '').strip().upper()
    if ticker:
        ticker_counter[ticker] += 1

print('combined_doc_index', out)
print('doc_count', len(rows))
print('ticker_count', len(ticker_counter))
print('tickers', ' '.join(sorted(ticker_counter.keys())))
PY

python -m scripts.build_index \
  --ingest-profile "${PROFILE}" \
  --ingest-output-dir "${TARGET_CHUNK_DIR}" \
  --postgres-schema "${SCHEMA}" \
  --postgres-dsn "${POSTGRES_DSN:-${DATABASE_URL:-}}" \
  --llm-provider openai \
  --dense-model "BAAI/bge-m3" \
  --dense-base-url "${OPENAI_EMBED_BASE_URL:-}" \
  --context none \
  --batch-size 128 \
  --sparse-search-method bm25 \
  --debug-sample-rate 0 \
  --reset-corpus \
  --recreate-ann-index

python - <<'PY'
from pathlib import Path

chunks = Path('data/ingest_profiles/eval_revamp_combined_20260217/sec_filings_md_secparser/chunked_1024_128/chunks')
print('chunk_files', len(list(chunks.glob('*.jsonl'))))
PY
