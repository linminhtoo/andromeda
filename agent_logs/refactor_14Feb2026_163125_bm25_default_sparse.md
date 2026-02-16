# Refactor Plan - BM25 Default Sparse Retrieval with FTS Fallback

## Objective
Make BM25 the default sparse ranking method, keep PostgreSQL full-text search (FTS) as an explicit alternative, and enforce strict index/retrieval method compatibility checks.

## Technical Approach
- Add an explicit sparse-search method setting (`bm25` or `fts`) to retrieval/indexing runtime surfaces.
- Implement method-specific sparse SQL in PostgreSQL hybrid retrieval.
- Persist sparse-method state in PostgreSQL schema metadata so retrieval/indexing can validate compatibility and fail fast on mismatches.
- Keep reset flows capable of intentionally switching methods by clearing sparse method state.

## Phases

### Phase 1 - Config plumbing and method typing
Acceptance criteria:
- Sparse method is typed and normalized in core DB/retriever code.
- Runtime app (`main.py`) can select method via env var and defaults to `bm25`.
- Index build CLI and shell wrapper can select method with `bm25` default.

### Phase 2 - Query/index behavior by method
Acceptance criteria:
- `bm25` path uses `pg_textsearch` BM25 ranking in sparse branch.
- `fts` path uses existing `ts_rank_cd` ranking branch.
- Schema/index bootstrap creates required sparse index artifacts for selected method.

### Phase 3 - Mismatch detection and error handling
Acceptance criteria:
- Sparse method used during indexing is persisted in DB metadata.
- Retrieval raises clear errors when configured method mismatches indexed method.
- Indexing raises clear errors on mismatch unless corpus reset has intentionally cleared state.
- `clear_all()` clears sparse method metadata to allow intentional rebuild with another method.

### Phase 4 - Docs/tests/changelog/logbook
Acceptance criteria:
- README and `.env.example` document method selection and defaults.
- CHANGELOG includes behavior change summary.
- Tests cover sparse method normalization/plumbing changes.
- `agent_logs/LOGBOOK.md` gets a new entry with observations and validation results.

## files_to_change
- `src/andromeda/db.py`
- `src/andromeda/retriever.py`
- `src/andromeda/main.py`
- `scripts/build_index.py`
- `scripts/build_index.sh`
- `.env.example`
- `README.md`
- `tests/test_retriever_postgres.py`
- `CHANGELOG.md`
- `agent_logs/LOGBOOK.md`

## new_files
- `agent_logs/refactor_14Feb2026_163125_bm25_default_sparse.md`

## Constraints and assumptions
- No DB migration framework is assumed; compatibility checks are implemented via SQL executed in existing bootstrap paths.
- No commit/push operations will be performed.
- Existing unrelated working-tree changes from other contributors will not be reverted.

## Potential add-ons (not in current scope)
- Add a dedicated CLI command to switch sparse method safely with automatic index cleanup.
- Add integration tests against a temporary PostgreSQL container that verify BM25 vs FTS execution paths and query plans.
