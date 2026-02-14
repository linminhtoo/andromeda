# Andromeda

Andromeda is a financial RAG assistant for SEC filings.
This codebase is now **PostgreSQL-first**:
- PostgreSQL is the source of truth for corpus data.
- PostgreSQL also handles hybrid retrieval (`pgvector` + full text search).
- Retrieval supports native pre-filtering by ticker/date to reduce false positives.

This rewrite intentionally removed backend sprawl:
- Removed Qdrant support.
- Removed Milvus support.
- Removed app-level OpenTelemetry/tracing modules.

Backward compatibility with old vector artifacts is not a goal. Rebuild the corpus/index from source files.

## Architecture

### Core runtime flow

```mermaid
flowchart LR
  UI[Web UI] --> API[FastAPI /query_stream]
  API --> RET[PostgresHybridRetriever]
  RET --> PG[(PostgreSQL + pgvector + FTS)]
  API --> RER[Cross-encoder reranker]
  API --> LLM[Chat LLM]
  LLM --> API
  API --> UI
```

### Ingestion/indexing flow

```mermaid
flowchart LR
  EDGAR[EDGAR filings] --> DL[scripts/download.py]
  DL --> H2M[scripts/process_html_to_markdown.py]
  H2M --> CH[scripts/chunk.py]
  CH --> BI[scripts/build_index.py]
  BI --> PG[(documents + chunks tables)]
```

## Data model (concise relational schema)

The refactor uses a minimal schema to keep joins simple and code maintainable.

### `documents`
- one row per canonical filing document
- key metadata used for filtering (`ticker`, `filing_date`, etc.)

### `chunks`
- one row per chunk
- dense vector in `embedding` (`pgvector`)
- lexical text in `retrieval_text` (indexed with generated `tsvector`)
- optional `retrieval_context` for contextual embeddings

```mermaid
erDiagram
  DOCUMENTS {
    text doc_id PK
    text ticker
    text company
    text cik
    text accession
    text filing_type
    date filing_date
    date period_end_date
    jsonb metadata
  }

  CHUNKS {
    text chunk_id PK
    text doc_id FK
    int chunk_index
    int page_no
    text[] headings
    text text
    text retrieval_text
    text retrieval_context
    vector embedding
    jsonb metadata
  }

  DOCUMENTS ||--o{ CHUNKS : contains
```

## Retrieval model

`PostgresHybridRetriever` combines:
- dense ranking: cosine distance on `embedding`
- sparse ranking: PostgreSQL FTS on `retrieval_text`
- fusion: weighted reciprocal-rank fusion (RRF)
- ANN index strategy: HNSW (pgvector)

Optional retrieval filters are applied before ranking:
- `tickers`
- `filing_date_from`
- `filing_date_to`

## Naming cleanup: `retrieval_text` and `retrieval_context`

Old code overloaded `index_text` and `context`.
The rewrite makes fields explicit:
- `retrieval_text`: text used for lexical retrieval and UI/source inspection
- `retrieval_context`: optional LLM-situated context
- embedding input is derived as:
  - `retrieval_text`
  - or `f"Context:\n{retrieval_context}\n\nChunk:\n{retrieval_text}"`

Database bootstrap includes a safety migration:
- `chunks.index_text -> chunks.retrieval_text`
- `chunks.context -> chunks.retrieval_context`

## Quickstart

Run commands from the repository root.

### 0) Environment

```bash
cp .env.example .env
```

Fill at least:
- `POSTGRES_DSN` (or `DATABASE_URL`)
- `OPENAI_API_KEY`
- model endpoint base URLs

Optional (recommended for experiment isolation on shared DBs):
- `POSTGRES_SCHEMA` (used by both indexing and runtime retrieval)

### 1) Start PostgreSQL (lightweight local option)

```bash
docker run --name andromeda-pg \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=andromeda \
  -p 5432:5432 \
  -d pgvector/pgvector:pg16
```

### 2) Ingestion + index build

```bash
./scripts/download.sh
./scripts/process_html_to_markdown.sh
./scripts/chunk.sh
./scripts/build_index.sh
```

### Safe experiment runs (shared Postgres)

If you run a shared Postgres instance (including a remote Docker host), use one schema per experiment.

Recommended env pattern:

```bash
POSTGRES_SCHEMA=exp_ctx_neighbors_w8_m24_ef200 \
RESET_CORPUS=true \
RECREATE_ANN_INDEX=true \
ANN_HNSW_M=24 \
ANN_HNSW_EF_CONSTRUCTION=200 \
bash scripts/build_index.sh
```

This keeps experiments isolated while reusing the same `POSTGRES_DSN`.

What each knob does:
- `POSTGRES_SCHEMA`: target schema for tables/indexes. If unset/empty, indexing uses the default schema (`public`).
- `RESET_CORPUS=true`: applies `--reset-corpus` and truncates `documents` + `chunks` in the selected schema.
- `RECREATE_ANN_INDEX=true`: drops and recreates ANN indexes in the selected schema.
- `ANN_HNSW_M`: HNSW graph connectivity. Higher typically improves recall but increases index memory/build cost.
- `ANN_HNSW_EF_CONSTRUCTION`: HNSW build-time search breadth. Higher typically improves recall but slows index build.

Safety behavior:
- If `POSTGRES_SCHEMA` is unset and you request destructive/index-recreate flags, the script exits early by default.
- To intentionally mutate default schema, set `ALLOW_DEFAULT_SCHEMA_MUTATIONS=true` (dangerous on production DSNs).

CLI equivalent (without shell env vars):

```bash
python -m scripts.build_index \
  --ingest-output-dir ./data/sec_filings_md_secparser/chunked_1024_128 \
  --postgres-dsn "$POSTGRES_DSN" \
  --postgres-schema exp_ctx_neighbors_w8_m24_ef200 \
  --context neighbors \
  --context-window 8 \
  --ann-hnsw-m 24 \
  --ann-hnsw-ef-construction 200 \
  --reset-corpus \
  --recreate-ann-index
```

Note: runtime retrieval also reads `POSTGRES_SCHEMA`, so set the same schema when serving/evaluating that experiment.

### 3) Start app

```bash
./scripts/launch_app.sh
```

`launch_app.sh` now compiles frontend TypeScript assets before starting Uvicorn.
Node.js/npm must be installed locally.

Open:
- Q&A: `http://localhost:8236/`
- Eval review UI: `http://localhost:8236/review`

### Frontend TypeScript build (manual)

```bash
npm install
npm run build:ts
```

Compiled assets are written to:
- `src/finrag/static/js/index/main.js`
- `src/finrag/static/js/review/main.js`
- additional page submodules under:
  - `src/finrag/static/js/index/`
  - `src/finrag/static/js/review/`

TypeScript source is now split into page-focused submodules:
- `src/finrag/static/ts/index/`
- `src/finrag/static/ts/review/`
- shared helpers in `src/finrag/static/ts/shared/`

## UI notes

### Q&A UI (`/`)
- Refreshed, cleaner non-purple visual theme with improved spacing/contrast.
- Progress panel now shows a per-step pipeline (`retrieve`, `rerank`, `draft`, `final`) plus a live event feed.
- History entries persist and display timing data (`timing_ms`) so step durations survive reloads.

### Review UI (`/review`)
- Refreshed visual theme aligned with the main Q&A UI.
- Case details include a dedicated "Generation timings" block when `generation.timing_ms` is available.

## Key scripts

- `scripts/process_html_to_markdown.py`
  - parses SEC filing HTML directly with `sec-parser` (no PDF/OCR roundtrip)
  - emits normalized markdown to `processed_markdown/`
  - writes per-file debug metadata to `debug/<filing>/metadata.json`

- `scripts/chunk.py`
  - default chunker is `markdown_table_preserving` to keep whole tables and heading sections
  - optional `docling_hybrid` chunker is still available for tokenizer-aware chunking

- `scripts/build_index.py`
  - reads chunk exports and upserts into PostgreSQL
  - supports schema-scoped indexing via `--postgres-schema` (or `POSTGRES_SCHEMA`)
  - supports context strategies (`none`, `document`, `neighbors`, `metadata`)
  - ANN is HNSW-only with optional tuning via `--ann-hnsw-m` and `--ann-hnsw-ef-construction`
  - supports `--reset-corpus` (`--truncate` alias), `--recreate-ann-index`, and `--skip-existing-chunks`
  - blocks destructive flags on default schema unless `--allow-default-schema-mutations` is explicitly set

- `scripts/run_eval.py`
  - runs eval queries through `RAGService.answer_question()`
  - writes `generations.jsonl`, `generation_summary.json`, `run_config.json`

- `scripts/inspect_collection.py`
  - inspects indexed chunks directly in PostgreSQL
  - supports chunk/ticker/date filters

## API filter support

`/query` and `/query_stream` accept:
- `tickers: list[str]`
- `filing_date_from: YYYY-MM-DD`
- `filing_date_to: YYYY-MM-DD`

These filters are enforced in SQL before dense/sparse candidate generation.

## Evaluation workflow

```bash
python3 scripts/make_eval_set.py \
  --ingest-output-dir ./data/sec_filings_md_v5/chunked_1024_128 \
  --out ./eval/eval_queries.jsonl

python3 -m scripts.run_eval \
  --eval-queries ./eval/eval_queries.jsonl \
  --out-dir ./eval/results \
  --mode normal \
  --concurrency 8

python3 -m scripts.score_eval --run-dir ./eval/results/eval_run.<...>
```

Review labels:
- run app or `bash scripts/launch_review.sh`
- open `http://localhost:8236/review`

## Breaking changes summary

- Qdrant removed.
- Milvus removed.
- App-level OpenTelemetry/tracing modules removed.
- Env vars like `RETRIEVER_BACKEND`, `MILVUS_*`, `QDRANT_*`, `FINRAG_OTEL_*`, `FINRAG_TRACES_*` are obsolete.
- `index_text` renamed to `retrieval_text`; `context` renamed to `retrieval_context`.
