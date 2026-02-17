# PostgreSQL-First Refactor Plan (11 Feb 2026)

## Goal
Rewrite `financial-rag` around a single, concise, maintainable retrieval stack:
- PostgreSQL as the system of record and retrieval engine
- Remove Qdrant support entirely
- Remove Milvus support entirely
- Remove OpenTelemetry/tracing modules and wiring that add code bloat
- Keep behavior focused, readable, and easy to extend

## Scope
This refactor intentionally does **not** preserve backward compatibility with prior vector-store artifacts.
Rebuilding via ingestion/chunk/index scripts is expected.

## Phase 1: Core DB + Retriever Rewrite

### Technical approach
1. Introduce a small PostgreSQL schema with minimal tables:
   - `documents`: one row per filing document
   - `chunks`: one row per chunk with text, metadata, and embedding (`pgvector`)
2. Implement a new `PostgresHybridRetriever` in `src/andromeda/retriever.py`:
   - Dense similarity using `pgvector` cosine distance
   - Sparse lexical retrieval via PostgreSQL FTS (`tsvector` + `plainto_tsquery`)
   - Hybrid score fusion in SQL using weighted normalized scores
   - Native filters at retrieval time: ticker list + filing date range
3. Keep reranker APIs stable for `RAGService` integration.

### Acceptance criteria
- No Qdrant/Milvus classes remain in retriever core
- Retrieval returns `ScoredChunk` with same shape used by QA pipeline
- Retrieval can constrain search with ticker/date filters

### Files to change
- `src/andromeda/retriever.py`
- `src/andromeda/dataclasses.py` (if needed for filter typing)
- `src/andromeda/main.py` (for filter plumb-through)

### New files
- `src/andromeda/db.py` (Postgres connection + schema init + helper queries)

## Phase 2: Index Build Pipeline Rewrite (PostgreSQL only)

### Technical approach
1. Rewrite `scripts/build_index.py` to:
   - Load chunk exports from `doc_index.jsonl` + chunk JSONL files
   - Upsert documents and chunks into PostgreSQL
   - Generate dense embeddings via existing `LLMClient`
   - Populate `search_text` and `tsvector` indexes
2. Add schema bootstrap + index creation in one place.
3. Remove all backend branching (`qdrant|milvus`).

### Acceptance criteria
- Script indexes corpus into PostgreSQL without any vector DB dependency
- `--expand-collection` behavior becomes straightforward idempotent upsert semantics
- Script logging/run summary remains clear and concise

### Files to change
- `scripts/build_index.py`
- `scripts/build_index.sh`

### New files
- `scripts/init_postgres.sh` (optional lightweight local bootstrap helper)

## Phase 3: App + Eval Wiring Cleanup

### Technical approach
1. Simplify `src/andromeda/main.py`:
   - Remove OTel imports/spans/status handling
   - Remove trace JSONL writing flow and related env toggles
   - Use only Postgres retriever construction
   - Add request-level retrieval filters (tickers/date range)
2. Update eval runner and run script env assumptions for Postgres-only operation.

### Acceptance criteria
- `/query` and `/query_stream` run without OTel/traces modules
- Eval generation still works with same output artifacts
- No runtime dependency on Milvus/Qdrant environment variables

### Files to change
- `src/andromeda/main.py`
- `src/andromeda/eval/runner.py`
- `scripts/run_eval.py`
- `scripts/run_eval.sh`
- `scripts/launch_app.sh`

### New files
- None required

## Phase 4: Dependency, Tests, and Repo Hygiene

### Technical approach
1. Update dependencies:
   - Remove `qdrant-client`, `pymilvus*`, OpenTelemetry packages
   - Add PostgreSQL dependencies (`psycopg`, optionally `pgvector` Python helper)
2. Replace obsolete tests:
   - Remove Qdrant + telemetry tests
   - Add retriever unit tests for hybrid ranking + ticker/date filtering (using mocked DB layer)
3. Remove dead scripts/files tied to eliminated systems.

### Acceptance criteria
- `pre-commit run --all` passes
- pytest suite passes (or remaining failures documented with actionable notes)
- imports no longer reference removed modules

### Files to change
- `pyproject.toml`
- `tests/test_retriever_qdrant_e2e.py` (replace)
- `tests/test_telemetry.py` (remove/replace)
- `tests/conftest.py` (remove OTel env coupling)
- `src/andromeda/llm_clients.py` (fastembed message cleanup)
- `.env.example`

### New files
- `tests/test_retriever_postgres.py`

## Phase 5: Documentation + Change Log + Logbook

### Technical approach
1. Update docs to reflect new architecture and commands:
   - PostgreSQL-only indexing/retrieval
   - Removal of Qdrant/Milvus/OTel paths
2. Update `CHANGELOG.md` with migration notes.
3. Append implementation observations/results to `experiments/LOGBOOK.md`.

### Acceptance criteria
- README quickstart matches executable commands
- Change log reflects breaking changes
- Logbook captures key decisions and validation outcomes

### Files to change
- `README.md`
- `CHANGELOG.md`
- `experiments/LOGBOOK.md`

### New files
- None required

## Suggested future work (not in current scope)
- Add SQL migrations tooling (Alembic or lightweight migration runner)
- Optional switchable reranker providers (API-based cross-encoders)
- Persist QA/eval runs in Postgres tables instead of JSONL artifacts
