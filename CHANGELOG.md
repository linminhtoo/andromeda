# Changelog

All notable changes to this package will be documented in
this file.

This format is based on [Keep a Changelog](https://keepachangelog.com/).

## Unreleased

### Added
- PostgreSQL-native data layer (`src/finrag/db.py`) with minimal corpus schema (`documents`, `chunks`) and pgvector/FTS indexes.
- PostgreSQL chunk inspection script (`scripts/inspect_collection.py`) with ticker/date filters.
- PostgreSQL retriever tests (`tests/test_retriever_postgres.py`).
- Indexing CLI flags for ANN tuning and reset flows: `--ann-hnsw-m`, `--ann-hnsw-ef-construction`, `--recreate-ann-index`, and `--reset-corpus` (with legacy `--truncate` alias).
- Indexing schema selector for experiment isolation on shared Postgres instances: `--postgres-schema` / `POSTGRES_SCHEMA`.
- History persistence now stores per-request step timing (`timing_ms`) for streaming runs (`retrieve_ms`, `rerank_ms`, `draft_ms`, `final_ms`, `total_ms`).
- Review UI timing panel for eval case details, sourced from `generation.timing_ms` when available.
- Frontend TypeScript build tooling (`package.json`, `tsconfig.json`) plus migrated TS sources for both UIs:
  - `src/finrag/static/ts/index/`
  - `src/finrag/static/ts/review/`
  - shared helpers in `src/finrag/static/ts/shared/`

### Changed
- Refactored retrieval/indexing to PostgreSQL-only backend (`PostgresHybridRetriever`).
- Reworked embedding text flow to use explicit `retrieval_text` + `retrieval_context` naming.
- Updated app and eval scripts for PostgreSQL runtime assumptions.
- Rewrote README to reflect PostgreSQL-first architecture and commands.
- Strengthened typing in core runtime paths by introducing typed metadata/row models and replacing ad-hoc dict metadata access in retrieval/QA/eval code.
- ANN index management now uses HNSW-only creation; ivfflat fallback creation was removed.
- Added safety guard to block destructive indexing flags on default schema unless explicitly overridden (`--allow-default-schema-mutations`).
- Runtime retriever now honors `POSTGRES_SCHEMA` so app queries can target experiment schemas consistently.
- Polished both web UIs (`/` and `/review`) with a cleaner visual system and improved readability.
- Replaced the old text-only progress display in `/` with a structured step pipeline + event feed, and surfaced timing summaries in history cards.
- Main/review HTML now load compiled JS module entrypoints (`/static/js/index/main.js`, `/static/js/review/main.js`) instead of inline scripts.
- Launch scripts now compile TypeScript frontend assets before starting servers.
- `launch_review.sh` now activates `.venv` before starting uvicorn, matching the main app launcher behavior.

### Fixed
- Contextual embedding flow now stores `retrieval_text` separately from `retrieval_context` instead of mixing both.

### Removed
- Qdrant backend and related tests/scripts.
- Milvus backend and related scripts.
- App-level OpenTelemetry/tracing modules and related tests/scripts.
- Legacy `index_text` references in core runtime/tests.

### Deprecated

### Dev
