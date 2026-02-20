# Plan: Reduce heuristic routing in query planner

## Scope
Update planner routing in `src/andromeda/query/runtime.py` so that:
- `clarification_required` never routes into `refuse_unindexed_ticker_candidates`.
- Heuristic ticker inference is no longer used in planner-first flow.
- If planner selects `answer` but no valid ticker list is available, return an early user-facing error and terminate.

## Phase 1: Runtime routing changes
- Files to change:
  - `src/andromeda/query/runtime.py`
- Technical approach:
  - Remove heuristic ticker inference fallback in `plan_query`.
  - Enforce explicit planner-output tickers for `action=answer`.
  - Keep clarification/refusal behavior explicit and deterministic from planner output.
  - Remove dead helper methods that only supported deprecated ticker-heuristic routing.
- Acceptance criteria:
  - No runtime path from `clarification_required` to `refuse_unindexed_ticker_candidates`.
  - `action=answer` with empty/invalid tickers returns early error message.

## Phase 2: Test updates
- Files to change:
  - `tests/test_query_runtime_tools_first.py`
- Technical approach:
  - Replace tests that expect heuristic ticker inference/refusal.
  - Add assertions for new behavior: clarification path stays clarification; answer-without-tickers fails early.
- Acceptance criteria:
  - Updated tests pass and cover the new routing constraints.

## Phase 3: Documentation + validation
- Files to change:
  - `CHANGELOG.md`
  - `agent_logs/LOGBOOK.md`
- Technical approach:
  - Record behavior change and rationale.
  - Run full required checks at end.
- Acceptance criteria:
  - `pytest tests/` passes.
  - `PRE_COMMIT_HOME=/tmp/pre-commit-cache pre-commit run --all` passes.

## Suggestions (not in this scope)
- Add a dedicated planner-output validation metric (ticker completeness by action) to CI eval checks.
