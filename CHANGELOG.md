# Changelog

All notable changes to this package will be documented in
this file.

This format is based on [Keep a Changelog](https://keepachangelog.com/).

## Unreleased

### Added
- PostgreSQL-native data layer (`src/finrag/db.py`) with minimal corpus schema (`documents`, `chunks`) and pgvector/FTS indexes.
- PostgreSQL chunk inspection script (`scripts/inspect_collection.py`) with ticker/date filters.
- PostgreSQL retriever tests (`tests/test_retriever_postgres.py`).

### Changed
- Refactored retrieval/indexing to PostgreSQL-only backend (`PostgresHybridRetriever`).
- Reworked embedding text flow to use explicit `retrieval_text` + `retrieval_context` naming.
- Updated app and eval scripts for PostgreSQL runtime assumptions.
- Rewrote README to reflect PostgreSQL-first architecture and commands.
- Strengthened typing in core runtime paths by introducing typed metadata/row models and replacing ad-hoc dict metadata access in retrieval/QA/eval code.

### Fixed
- Contextual embedding flow now stores `retrieval_text` separately from `retrieval_context` instead of mixing both.

### Removed
- Qdrant backend and related tests/scripts.
- Milvus backend and related scripts.
- App-level OpenTelemetry/tracing modules and related tests/scripts.
- Legacy `index_text` references in core runtime/tests.

### Deprecated

### Dev
