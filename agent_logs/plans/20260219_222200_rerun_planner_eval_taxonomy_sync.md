# Planner Eval Taxonomy Sync + Rerun (2026-02-19)

## Scope
Update planner evaluation artifacts to match current runtime characteristics, then rerun the planner evaluation suite and report the updated metrics.

## Phase 1: Align planner eval taxonomy with runtime
Acceptance criteria:
- `PlannerEvalCharacteristic` contains only characteristics currently used in runtime logic.
- Planner dataset builder compiles without references to removed characteristics.
- Existing JSONL planner eval dataset labels are migrated to current taxonomy.

files_to_change:
- `src/andromeda/eval/planner_schema.py`
- `src/andromeda/eval/planner_dataset.py`
- `eval/eval_queries_planner_characteristics_manual100_20260219.jsonl`

new_files:
- none

## Phase 2: Execute planner eval suite and collect outputs
Acceptance criteria:
- Planner run completes and writes run artifacts under `eval/results_planner/`.
- Score summary and review CSV are generated.
- Key metrics are summarized for handoff.

files_to_change:
- none (new run artifacts only)

new_files:
- run artifact directory under `eval/results_planner/`

## Notes / future follow-up (not in current scope)
- Add an automated dataset consistency check that fails if eval taxonomy diverges from runtime taxonomy.
