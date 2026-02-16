# Eval Resume Plan - 16 Feb 2026 (Dashboard + 8-thread rerun)

## Objective
1) Re-run holistic single-ticker eval using tools-enabled pipeline with 8 thread workers and normal preset token/retrieval budgets.
2) Build an experiment dashboard/harness to visualize metric changes across eval runs.

## Phase 1 - Re-run single holistic eval
Acceptance criteria:
- Fresh single-ticker run with `mode=normal`, tools enabled, `concurrency=8`, `parallel_backend=thread` completes.
- Score summary is produced and compared to prior baseline.

files_to_change:
- none (execution only)
new_files:
- `agent_logs/20260216_*_eval_single_*.sh` run script

## Phase 2 - Build dashboard/harness
Acceptance criteria:
- A script can scan `eval/results_revamp/single/eval_run.*` and aggregate key metrics.
- Script outputs both CSV and HTML dashboard with sortable/comparable experiment rows and selected metric deltas.
- Script can be re-run as new experiments are added.

files_to_change:
- `scripts/` (new dashboard script)
new_files:
- `scripts/eval_dashboard.py`
- generated artifacts under `eval/results_revamp/dashboard/`

## Phase 3 - Log and document
Acceptance criteria:
- `agent_logs/LOGBOOK.md` appended with new experiment results and dashboard usage.
- `CHANGELOG.md` updated for new dashboard utility.

files_to_change:
- `agent_logs/LOGBOOK.md`
- `CHANGELOG.md`
new_files:
- run scripts under `agent_logs/`
