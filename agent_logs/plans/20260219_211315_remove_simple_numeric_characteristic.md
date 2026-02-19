# Plan: Remove `simple_numeric` planner characteristic and tighten planner taxonomy

## Phase 1: Runtime taxonomy and prompt update
Acceptance criteria:
- `QueryCharacteristic` no longer contains `SIMPLE_NUMERIC`.
- Planner prompt/few-shot examples in `src/andromeda/query/runtime.py` use only non-redundant characteristics.
- Prompt includes clear characteristic definitions to reduce overlap ambiguity.

files_to_change:
- `src/andromeda/query/runtime.py`

new_files:
- none

## Phase 2: Fallback heuristic compatibility
Acceptance criteria:
- Fallback heuristic classification no longer emits `simple_numeric`.
- No runtime fallback path can raise enum-conversion errors due to removed characteristic.

files_to_change:
- `src/andromeda/query/planner_heuristics.py`

new_files:
- none

## Phase 3: Test updates + validation
Acceptance criteria:
- Tests referencing `QueryCharacteristic.SIMPLE_NUMERIC` are updated.
- `pytest tests/` passes.
- `PRE_COMMIT_HOME=/tmp/pre-commit-cache pre-commit run --all` passes.

files_to_change:
- `tests/test_query_runtime_tools_first.py`
- `tests/test_planner_eval_pipeline.py`
- `agent_logs/LOGBOOK.md`

new_files:
- none

## Suggested follow-ups (not in this change)
- Remove `simple_numeric` from planner-eval schema/dataset as a separate migration with updated baseline metrics.
- Re-run planner benchmark after taxonomy migration to establish new reference numbers.
