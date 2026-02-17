# Stronger Typing Refactor Plan (12 Feb 2026)

## Goal
Reduce weakly-typed dictionary plumbing in core runtime paths by introducing explicit typed models/parsers and replacing ad-hoc `.get()` lookups.

## Scope
Focus on high-impact, high-churn modules used in ingestion/indexing/retrieval/QA/eval:
- retrieval + DB row mapping
- chunk metadata access in QA/main/eval
- build-index input parsing

This phase does **not** attempt to fully type every historical script/module.

## Phase 1: Typed metadata models

### Technical approach
1. Add a dedicated metadata model module with:
   - `DocumentMetadata`
   - `ChunkMetadata`
   - safe parser helpers (`from_value`, `from_mapping`)
2. Keep `DocChunk.metadata` wire format as dict for compatibility, but parse once and use typed attributes downstream.

### Acceptance criteria
- Core code paths stop using naked dict access for known metadata fields.
- Known keys (`doc`, `retrieval_text`, `retrieval_context`, `summary`, etc.) are accessed through typed objects.

### files_to_change
- `src/andromeda/retriever.py`
- `src/andromeda/main.py`
- `src/andromeda/qa.py`
- `src/andromeda/eval/generation.py`
- `src/andromeda/eval/scoring.py`
- `src/andromeda/chunk_postprocess.py`

### new_files
- `src/andromeda/metadata_models.py`

## Phase 2: Typed retrieval row and build-index parsing

### Technical approach
1. Add typed retrieval row model in DB layer and return that from `hybrid_search`.
2. Replace dict-based mapping in retriever with typed row inputs.
3. Add typed parsers for build-index JSONL entries/chunks.

### Acceptance criteria
- `retrieve_hybrid` flow no longer reads SQL result rows via `.get()`.
- `scripts/build_index.py` uses typed entry parsing for expected fields.

### files_to_change
- `src/andromeda/db.py`
- `src/andromeda/retriever.py`
- `scripts/build_index.py`

### new_files
- none

## Phase 3: Validation + notes

### Technical approach
1. Run formatting/lint/type hooks.
2. Run tests.
3. Append concise findings/results in `experiments/LOGBOOK.md`.

### Acceptance criteria
- `pre-commit run --all` passes.
- `pytest tests/` passes.
- Logbook updated with outcomes and limitations.

### files_to_change
- `experiments/LOGBOOK.md`

### new_files
- optional validation script under `experiments/` (if needed)

## Suggested future work (not in this scope)
- Migrate `DocChunk.metadata` to a fully typed object across entire codebase.
- Introduce typed wrappers for eval score/review CSV rows.
- Add stricter JSON schema validation for on-disk artifacts.
