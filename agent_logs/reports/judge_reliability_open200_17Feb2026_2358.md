# Judge Reliability Improvement Plan (Open-Ended 200 Pool)

Date: 2026-02-17

## Objective
Improve reliability of `faithfulness_v1` judge decisions (reduce false positive fail calls) using a larger and more diverse open-ended eval pool, then iterate judge prompt/harness with a strict dev/test protocol.

## Constraints and principles
- Keep eval runtime aligned with deployed settings (`mode=normal`, tools enabled, no refine, `judge_context_chars=80000`).
- Use data-driven iteration: audit real failure decisions, target concrete judge error patterns.
- Commit and LOGBOOK update after every iteration (`N=1`).

## Phase 1: Expand open-ended pool to 200 and run baseline
Acceptance criteria:
- New open-ended query set with `n=200` generated from current ingest profile.
- Diversity summary recorded (ticker count, family count).
- Baseline generation + scoring run completed.
- Failure pool count and initial breakdown captured.

files_to_change:
- agent_logs/20260217_*.sh (new run scripts)
- eval/ (new query file + run artifacts)
- agent_logs/LOGBOOK.md

new_files:
- agent_logs/20260217_*_generate_openended200_*.sh
- agent_logs/20260217_*_eval_openended200_judgebaseline_*.sh

## Phase 2: Build/refresh labeled judge audit set with dev/test split
Acceptance criteria:
- Build decision-level audit CSV from baseline run (faithfulness focus).
- Manually label enough decisions to support dev/test evaluation (including both fail and pass predictions).
- Produce split-aware reliability report (dev + test metrics).

files_to_change:
- agent_logs/ (audit helper scripts / outputs)
- eval/results_revamp/open/*/review.csv
- agent_logs/LOGBOOK.md

new_files:
- agent_logs/20260217_*_prepare_open200_judge_audit.sh
- agent_logs/judge_audit_open200_*.csv
- agent_logs/judge_reliability_open200_baseline_*.json

## Phase 3: Judge iteration loop (>=2 iterations)
Acceptance criteria per iteration:
- One targeted judge improvement implemented (prompt and/or harness).
- Re-score fixed generations from baseline run.
- Evaluate against same labeled dev/test split.
- Record metrics deltas, error taxonomy, and decision in LOGBOOK.
- Commit the iteration changes and reference commit hash in LOGBOOK entry.

files_to_change:
- src/andromeda/eval/judges.py (prompt/harness updates)
- scripts/score_eval.py and/or scripts/judge_reliability.py (if harness changes needed)
- agent_logs/LOGBOOK.md

## Phase 4: Wrap-up summary
Acceptance criteria:
- Final recommendation of best judge version based on held-out test alignment.
- Clear reproducibility steps and artifact paths logged.

files_to_change:
- agent_logs/LOGBOOK.md

## Suggested future work (not in current scope)
- Add ensemble/consensus judge mode (multi-pass + majority vote) with bounded latency budget.
- Add explicit date/period normalization preprocessor for judge context.
- Add table-aware evidence extraction utility for judge prompts.
