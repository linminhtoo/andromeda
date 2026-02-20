# Doc Index Path Guardrails (2026-02-20)

## Objective
Verify whether `FINRAG_DOC_INDEX_PATH` from `.env` caused the wrong index path to be used in `BENCHMARK_WITH_FIXED_PLANNER_20Feb.md`, and prevent recurrence.

## Files to change
- `agent_logs/scripts/20260219_2358_run_full_suite_rerank_material_ablation.sh`
- `scripts/_env.sh` (if needed for shared resolution helpers)
- `.env.example`
- `BENCHMARK_WITH_FIXED_PLANNER_20Feb.md` (clarify root cause and fix)
- `agent_logs/LOGBOOK.md`

## New files
- none

## Approach
1. Verify root cause:
   - inspect benchmark note around line 194,
   - inspect script path-resolution logic,
   - inspect runtime artifacts (`run_config`, logs, and env default behavior) to confirm override.
2. Implement prevention:
   - default to ingest-profile derived doc index path,
   - do not silently use stale `FINRAG_DOC_INDEX_PATH` from `.env`,
   - add explicit opt-in override variable and clear warning/error checks.
3. Update docs:
   - remove/deprecate `FINRAG_DOC_INDEX_PATH` from `.env.example`.
4. Validate with tests + pre-commit.

## Acceptance criteria
- Root cause is explicitly verified with concrete evidence.
- Future benchmark scripts cannot silently pick a stale doc index from `.env`.
- `.env.example` no longer promotes `FINRAG_DOC_INDEX_PATH`.
- Changes recorded in `LOGBOOK.md` and benchmark report note updated.
