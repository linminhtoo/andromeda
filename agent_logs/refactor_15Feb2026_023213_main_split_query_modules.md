# main.py Query-Module Split Plan (15Feb2026 02:32:13)

## Goal
Reduce `src/andromeda/main.py` size and complexity by moving query orchestration logic into dedicated modules while keeping `main.py` focused on API endpoint wiring/public surface.

## Technical approach
1. Create a query runtime module containing:
- query request/response models
- tools-first planner dataclasses
- `RAGService` pipeline executor and response builder
- shared stream-stage token helper
- query status constants
2. Create a conversation-state module containing multi-turn conversation storage/merge/update helpers.
3. Update `main.py` to import these modules and keep endpoint handlers plus app wiring only.
4. Preserve existing API behavior and test coverage.

## Phases

### Phase 1: Extract query runtime
Acceptance criteria:
- `RAGService` and related planning/response dataclasses are moved out of `main.py`.
- `main.py` still exposes `/query` and `/query_stream` with unchanged payload contracts.

### Phase 2: Extract conversation state
Acceptance criteria:
- Conversation-id resolution/update logic is moved out of `main.py` into a dedicated module.
- Endpoints call conversation module utilities.

### Phase 3: Integrate and validate
Acceptance criteria:
- `main.py` no longer contains core tools-first pipeline implementation details.
- Full validation passes:
  - `pre-commit run --all`
  - `pytest -vvv tests/`
  - `python scripts/test_vllm_tool_call_openai.py --max-tokens 96 --tool-choice auto`

## files_to_change
- `src/andromeda/main.py`
- `CHANGELOG.md`
- `agent_logs/LOGBOOK.md`

## new_files
- `src/andromeda/query_runtime.py`
- `src/andromeda/query_conversation.py`
- `agent_logs/refactor_15Feb2026_023213_main_split_query_modules.md`

## Out of scope
- Splitting non-query concerns (ingestion/background job wiring/source endpoints/history endpoints) in this pass.
- API contract redesign.

## Future work (suggestion only)
- Extract history and source-view utilities from `main.py` into dedicated endpoint modules.

## Execution notes (implemented)
- Completed beyond initial scope: extracted additional endpoint-adjacent concerns to keep `main.py` API-focused.
  - `src/andromeda/query_streaming.py`
  - `src/andromeda/history_store.py`
  - `src/andromeda/source_access.py`
  - `src/andromeda/ingested_companies.py`
