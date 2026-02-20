# 20260219 Benchmark Follow-ups Implementation Plan

## Objective
Implement the immediate follow-ups listed in `BENCHMARK_REDUCED_HEURISTICS.md` without requiring live vLLM calls.

## Scope
1. Improve multi-ticker comparison answer planning with explicit output structure.
2. Tighten refusal behavior for out-of-scope tickers to avoid clarification loops.
3. Strengthen eval retry/continue safeguards for long-tail timeout behavior.

## Technical Approach

### Phase 1: Comparison structure guidance
- Carry planner characteristics into `PlannedQuery`.
- Use this signal to mark comparison-style multi-ticker synthesis.
- Extend multi-ticker synthesis/refine prompt builders with explicit comparison output contract:
  - decision summary
  - side-by-side table
  - evidence-backed winner/uncertainty section.

Acceptance criteria:
- Multi-ticker comparison plans preserve characteristic signal into generation phase.
- Prompt text contains explicit structured comparison requirements when applicable.
- Unit tests cover the new prompt contract.

### Phase 2: Stricter out-of-scope ticker refusal
- Add fallback utility that uses yfinance search to detect ticker-like candidates mentioned in the question, even when not indexed.
- In `plan_query`, when planner requests clarification and no indexed ticker is available, refuse directly if unindexed candidates are detected.
- Return explicit refusal message with candidate symbols and guidance to ingest/index first.

Acceptance criteria:
- Clarification loop is bypassed for detected unindexed ticker candidates.
- Existing behavior for indexed/ambiguous queries remains intact.
- Unit tests validate refusal path.

### Phase 3: Retry/continue hardening in eval runner
- Add retry timeout multiplier so follow-up attempt can run with a larger timeout budget.
- Record timeout budget used per attempt in generation settings for postmortems.
- Keep continue-on-error behavior unchanged and explicit.

Acceptance criteria:
- Retries use larger timeout window when configured.
- Per-query settings include timeout/retry telemetry.
- Unit tests verify retry timeout scaling.

## files_to_change
- `src/andromeda/query/runtime.py`
- `src/andromeda/query/planner_heuristics.py`
- `src/andromeda/llm/qa.py`
- `src/andromeda/eval/runner.py`
- `tests/test_query_runtime_tools_first.py`
- `tests/test_qa.py`
- `tests/test_eval_runner.py`
- `CHANGELOG.md`
- `agent_logs/LOGBOOK.md`

## new_files
- `agent_logs/plans/20260219_benchmark_followups_impl.md`
- `agent_logs/scripts/eval/20260219_followups_validation.sh`

## Future add-ons (not in current scope)
- Add small deterministic fallback formatter for comparison answers when model output violates structure.
- Add optional queue-aware scheduler for eval runner to cap concurrent long-tail retries.
