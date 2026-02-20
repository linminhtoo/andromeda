# Clarification vs Refusal Boundary + Planner Eval Sync (2026-02-19)

## Scope
Make planner behavior explicit and consistent:
- `clarification_required` => relevant query but unresolved ambiguity; return no characteristics.
- `refused` => out-of-scope/irrelevant query.
Then update the manual planner eval dataset labels to match this policy and rerun planner evaluation.

## Phase 1: Runtime planner policy update
Acceptance criteria:
- Planner prompt explicitly distinguishes clarification vs refusal.
- Prompt instructs `characteristics=[]` when action is clarification_required.
- Runtime normalizes planner outputs so clarification paths carry empty characteristics.

files_to_change:
- `src/andromeda/query/runtime.py`

new_files:
- none

## Phase 2: Eval dataset sync
Acceptance criteria:
- Clarification rows in manual planner eval dataset use empty expected characteristics.
- Regenerated JSONL reflects updated labels.

files_to_change:
- `src/andromeda/eval/planner_dataset.py`
- `eval/eval_queries_planner_characteristics_manual100_20260219.jsonl`

new_files:
- none

## Phase 3: Validation + rerun
Acceptance criteria:
- Planner eval suite runs successfully on updated dataset.
- Summary metrics and behavior deltas are captured in `LOGBOOK.md`.

files_to_change:
- `agent_logs/LOGBOOK.md`
- `CHANGELOG.md`

new_files:
- planner eval run artifacts under `eval/results_planner/`
