# Changelog

All notable changes to this package will be documented in
this file.

This format is based on [Keep a Changelog](https://keepachangelog.com/).

## Unreleased

### Added

### Changed

### Fixed

### Deprecated

### Dev


## v1.6.0 - 14 Feb 2026
### Added
- Sparse retrieval method selection across runtime and indexing:
  - `POSTGRES_SPARSE_SEARCH_METHOD` env var
  - `--sparse-search-method` in `scripts/build_index.py`
- Probabilistic chunk-level debug logging for indexing transparency in `scripts/build_index.py`:
  - `--debug-sample-rate` to randomly sample chunks for full payload logs
  - `--debug-max-samples` to cap sampled logs per run
  - `--debug-sample-seed` for deterministic sampling
  - sampled payload includes original text, retrieval fields, embedding text, embedding dimension/preview, and metadata
- Context-situating token budget controls for indexing:
  - `--context-max-tokens` in `scripts/build_index.py`
  - `CONTEXT_MAX_TOKENS` passthrough in `scripts/build_index.sh`
- Playwright UI automation harness for the main `/` app:
  - `playwright.config.ts`
  - npm scripts: `test:ui`, `test:ui:headed`, `playwright:install`
  - deterministic mocked interaction tests in `tests/ui/index.spec.ts`
- Fast frontend unit-test layer with Vitest:
  - `vitest.config.ts`
  - npm scripts: `test:unit`, `test:unit:watch`
  - focused unit suites for `markdown.ts` and `citations.ts` in `tests/ui-unit/`
- Ticker-only on-the-fly ingestion background jobs in the API:
  - `POST /ingest` now accepts JSON payload with one or more tickers (`{ticker, per_company}` or `{tickers, per_company}`)
  - `GET /ingest/{job_id}` returns lifecycle status for polling
  - new backend orchestration module `src/finrag/ingestion_jobs.py` runs:
    `download -> process_html_to_markdown -> chunk -> build_index`
- Durable ingest-profile storage on disk (`data/ingest_profiles/*.json`) with step-level settings capture for:
  - `scripts/download.py`
  - `scripts/process_html_to_markdown.py`
  - `scripts/chunk.py`
  - `scripts/build_index.py`
- Main UI controls for ticker ingestion:
  - ticker + files/company inputs
  - ingestion status pill/message
  - automatic status polling and ingested-company panel refresh on success

### Changed
- Default sparse ranking method is now BM25 (`pg_textsearch`) with PostgreSQL FTS as an explicit alternative.
- Retrieval/indexing now enforce sparse-method compatibility per schema and raise clear errors on mismatches.
- Context-situating LLM calls now apply an explicit generation cap (`max_tokens=256`) to keep summaries bounded.
- On-the-fly ingestion now reuses active runtime settings for schema compatibility:
  - PostgreSQL DSN/schema
  - sparse method
  - context strategy/window/metadata key
  - embedding/context LLM provider + model/base URL settings
- On-the-fly ingestion now loads settings from persisted ingest profiles first (schema/profile scoped), then falls back to env defaults.
- Ingestion now supports multiple tickers in one job request (`tickers` array), while retaining single-`ticker` compatibility.
- `scripts/build_index.sh` now sources `--context` and `--context-window` from env (`CONTEXT_STRATEGY`, `CONTEXT_WINDOW`) instead of hardcoded literals.
- `scripts/chunk.sh` now sources chunk sizing from env (`CHUNK_MAX_TOKENS`, `CHUNK_OVERLAP_TOKENS`) instead of hardcoded literals.
- Main query UI now defaults to a more compact layout:
  - progress activity feed is collapsed by default
  - draft panel is hidden by default for non-refine modes
  - layout width and answer readability spacing were tightened
- QA citation prompting now explicitly asks for chunk-level inline citations in the form `[doc=... chunk=...]`.

### Fixed
- Citation links in answers now honor `chunk=` hints (when present) and jump to the matching highlighted chunk in source viewer.
- Markdown thematic breaks (`---`, `***`, `___`) now render as horizontal rules in answer panes.

### Removed
- Legacy upload+OCR ingestion API contract (`file` upload + `use_mistral_ocr` flag) from `/ingest`.

### Dev
- Pre-commit now runs frontend Vitest unit tests (`frontend-unit-tests`) for static UI/TypeScript changes.
- Pre-push now runs Playwright browser-flow checks (`frontend-ui-tests`) for frontend/UI changes.


## v1.5.0 - 14 Feb 2026
### Added
- Indexing schema selector for experiment isolation on shared Postgres instances: `--postgres-schema` / `POSTGRES_SCHEMA`.
- Frontend TypeScript build tooling (`package.json`, `tsconfig.json`) plus migrated TS sources for both UIs:
  - `src/finrag/static/ts/index/`
  - `src/finrag/static/ts/review/`
  - shared helpers in `src/finrag/static/ts/shared/`

### Changed
- Main/review HTML now load compiled JS module entrypoints (`/static/js/index/main.js`, `/static/js/review/main.js`) instead of inline scripts.
- Launch scripts now compile TypeScript frontend assets before starting servers.
- `launch_review.sh` now activates `.venv` before starting uvicorn, matching the main app launcher behavior.
- Added safety guard to block destructive indexing flags on default schema unless explicitly overridden (`--allow-default-schema-mutations`).
- Runtime retriever now honors `POSTGRES_SCHEMA` so app queries can target experiment schemas consistently.


## v1.4.0 - 13 Feb 2026
### Added
- PostgreSQL-native data layer (`src/finrag/db.py`) with minimal corpus schema (`documents`, `chunks`) and pgvector/FTS indexes.
- PostgreSQL chunk inspection script (`scripts/inspect_collection.py`) with ticker/date filters.
- PostgreSQL retriever tests (`tests/test_retriever_postgres.py`).
- Indexing CLI flags for ANN tuning and reset flows: `--ann-hnsw-m`, `--ann-hnsw-ef-construction`, `--recreate-ann-index`, and `--reset-corpus` (with legacy `--truncate` alias).
- History persistence now stores per-request step timing (`timing_ms`) for streaming runs (`retrieve_ms`, `rerank_ms`, `draft_ms`, `final_ms`, `total_ms`).
- Review UI timing panel for eval case details, sourced from `generation.timing_ms` when available.

### Changed
- Refactored retrieval/indexing to PostgreSQL-only backend (`PostgresHybridRetriever`).
- Reworked embedding text flow to use explicit `retrieval_text` + `retrieval_context` naming.
- Updated app and eval scripts for PostgreSQL runtime assumptions.
- Rewrote README to reflect PostgreSQL-first architecture and commands.
- Strengthened typing in core runtime paths by introducing typed metadata/row models and replacing ad-hoc dict metadata access in retrieval/QA/eval code.
- ANN index management now uses HNSW-only creation; ivfflat fallback creation was removed.
- Polished both web UIs (`/` and `/review`) with a cleaner visual system and improved readability.
- Replaced the old text-only progress display in `/` with a structured step pipeline + event feed, and surfaced timing summaries in history cards.

### Fixed
- Contextual embedding flow now stores `retrieval_text` separately from `retrieval_context` instead of mixing both.

### Removed
- Qdrant backend and related tests/scripts.
- Milvus backend and related scripts.
- App-level OpenTelemetry/tracing modules and related tests/scripts.
- Legacy `index_text` references in core runtime/tests.
