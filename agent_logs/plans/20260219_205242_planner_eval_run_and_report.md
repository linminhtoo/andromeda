# Plan: Planner Eval Commits + Live Benchmark Report

## Phase 1: Commit planner-eval pipeline additions
Acceptance criteria:
- New planner-eval code, tests, and docs are committed in a focused commit.
- Unrelated working tree changes are not reverted.

files_to_change:
- none (commit staging only)

new_files:
- none

## Phase 2: Run planner eval against live vLLM
Acceptance criteria:
- Full planner eval run completes (or partial run captured with explicit failure notes).
- Scored artifacts exist (`planner_score_summary.json`, `planner_review.csv`, markdown summary).

files_to_change:
- `agent_logs/scripts/eval/` (run script if needed)

new_files:
- `agent_logs/scripts/eval/<timestamp>_run_planner_eval_suite_live.sh`

## Phase 3: Analyze results and write benchmark report
Acceptance criteria:
- `BENCHMARK_PLANNER.md` added with experiment definition, configuration, topline metrics, confusion/failure analysis, and surprising findings.
- `agent_logs/LOGBOOK.md` updated with commands, artifact paths, and observations.
- Report-style matches existing benchmark docs.

files_to_change:
- `BENCHMARK_PLANNER.md`
- `agent_logs/LOGBOOK.md`

new_files:
- `BENCHMARK_PLANNER.md`

## Phase 4: Commit benchmark/report updates
Acceptance criteria:
- Benchmark/report/logbook/run-script changes are committed in a second focused commit.
- Final response includes commit hashes and artifact locations.

files_to_change:
- none (commit staging only)

new_files:
- none

## Suggested follow-ups (not in current scope)
- Add trend aggregation of planner eval runs into dashboard format.
- Add manual audit checklist template for planner false-positive/false-negative cases.
