# Judge Alignment Plan (17 Feb 2026)

## Goal
Improve judge reliability before further pipeline iterations, with emphasis on metrics that currently have non-zero failure rates and a less-strict (materiality-aware) faithfulness criterion.

## Current target metrics (non-zero fail rates)
- `open_ended.faithfulness_v1`
- `factual.factual_correctness_v1`
- `factual.helpfulness_v1`
- `distractor.focus_v1`

## Phase 1: Build auditable judge-label dataset
Acceptance criteria:
- A per-decision labeling file exists for each target judge.
- Every target decision is manually adjudicated as judge-correct vs judge-incorrect.

Approach:
- Use existing run artifacts (`cases.jsonl`, `review.csv`) from latest stable run.
- Expand open-ended coverage by adding an open-ended-only run (larger sample).
- Export decision-level rows (`query_id`, `judge_id`, model prediction, explanation, question, answer, compact evidence).
- Manually label each decision (`gold_fail_label`, `judge_correct`).

files_to_change:
- `scripts/` (new judge-audit helper script)
- `agent_logs/` (manual labeling scripts + outputs)
- `agent_logs/LOGBOOK.md`

new_files:
- `scripts/judge_reliability.py`
- `agent_logs/*judge_audit*`

## Phase 2: Dev/Test judge alignment evaluation
Acceptance criteria:
- Stratified dev/test splits generated and frozen.
- Alignment metrics (precision/recall/F1/kappa) computed for dev and test for each target judge.
- Bootstrap confidence intervals reported for key rates.

Approach:
- Use manual labels as source of truth.
- Evaluate baseline prompt behavior on dev/test.
- Use bootstrap resampling for uncertainty on fail-rate and error deltas.

files_to_change:
- `scripts/judge_reliability.py`
- `agent_logs/LOGBOOK.md`

## Phase 3: Prompt iteration (judge-only)
Acceptance criteria:
- One or more prompt revisions trialed on dev only.
- Best candidate evaluated once on held-out test.
- Selected prompt is justified by non-regression and better alignment.

Approach:
- Add `faithfulness_v2` with materiality-aware tolerance (minor/peripheral deviations allowed).
- Keep generation pipeline fixed; only judge prompt/harness changes.
- Record per-iteration commit hash + metrics in LOGBOOK immediately after each iteration.

files_to_change:
- `src/andromeda/eval/judges.py`
- `scripts/score_eval.py` (if override controls are needed)
- `scripts/judge_reliability.py`
- `agent_logs/LOGBOOK.md`

## Suggestions (future, not in this scope)
- Pairwise consensus judging (2-judge committee with tie-break) for high-stakes metrics.
- Periodic calibration set refresh to avoid drift.
