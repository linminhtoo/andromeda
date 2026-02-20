# Helpfulness Failure Analysis Plan (2026-02-20)

## Objective
Explain why helpfulness failure remains high in the post-fix benchmark and add concrete, query-level examples to `BENCHMARK_WITH_FIXED_PLANNER_20Feb.md`.

## Files To Change
- `BENCHMARK_WITH_FIXED_PLANNER_20Feb.md`
- `agent_logs/LOGBOOK.md`

## New Files
- `agent_logs/scripts/20260220_0515_analyze_helpfulness_failures.py`
- `agent_logs/reports/20260220_helpfulness_failure_examples.md`

## Approach
1. Extract helpfulness-fail cases from scored baseline runs used in the report:
   - single100 baseline
   - multi60 baseline
   - open200 baseline
2. Summarize dominant failure patterns using judge explanations and answer traces.
3. Manually inspect representative failures and record concrete examples (query + short answer excerpt + judge rationale + diagnosis).
4. Update benchmark report with:
   - why rates remain high,
   - distribution by suite,
   - cited examples,
   - targeted next-step recommendations.
5. Log the experiment and script paths in `LOGBOOK.md`.

## Acceptance Criteria
- `BENCHMARK_WITH_FIXED_PLANNER_20Feb.md` contains an explicit section on helpfulness failure causes with specific, traceable examples (query IDs and run dirs).
- Analysis artifacts are saved under `agent_logs/`.
- `LOGBOOK.md` has an entry summarizing what was analyzed and what was learned.
