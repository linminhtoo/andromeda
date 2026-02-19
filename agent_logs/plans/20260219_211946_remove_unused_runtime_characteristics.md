# Plan: Remove unused runtime planner characteristics

## Phase 1: Runtime taxonomy cleanup
Acceptance criteria:
- `QueryCharacteristic` contains only characteristics used by runtime behavior.
- `period_scoped` is removed from runtime enum and planner prompt/few-shot examples.

files_to_change:
- `src/andromeda/query/runtime.py`

new_files:
- none

## Phase 2: Fallback classifier cleanup
Acceptance criteria:
- Fallback heuristics no longer emit removed characteristics.
- No enum conversion path can reference removed labels.

files_to_change:
- `src/andromeda/query/planner_heuristics.py`

new_files:
- none

## Phase 3: Test + docs updates
Acceptance criteria:
- Runtime tests are updated for new characteristic set.
- `CHANGELOG.md` and `agent_logs/LOGBOOK.md` include concise lineage notes.

files_to_change:
- `tests/test_query_runtime_tools_first.py`
- `CHANGELOG.md`
- `agent_logs/LOGBOOK.md`

new_files:
- none

## Phase 4: Validation
Acceptance criteria:
- `pytest tests/` passes.
- `PRE_COMMIT_HOME=/tmp/pre-commit-cache pre-commit run --all` passes.

files_to_change:
- none

new_files:
- none
