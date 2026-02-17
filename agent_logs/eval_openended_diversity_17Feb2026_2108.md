# Open-Ended Eval Improvement Plan (17 Feb 2026)

## Goal
Reduce open-ended `faithfulness_v1` fail rate while preserving/openly tracking `helpfulness_v1`, using a more diverse open-ended eval dataset and iterative answering-pipeline improvements.

## Constraints
- Match deployed settings as closely as possible.
- Evaluate only open-ended for this loop (skip refusal/distractor/comparison/factual).
- Use `concurrency=12` for generation and `judge-workers=12` for scoring.
- Use `--query-timeout-s 350` and `--judge-timeout-s 350`.
- Keep commit-per-iteration and append LOGBOOK after each iteration with commit hashes.

## Phase 1: Dataset Diversity Expansion
Acceptance criteria:
- Open-ended template/question space is materially broadened (not just small wording tweaks).
- Can generate an open-ended-only eval set with at least 100 unique questions.
- Generated questions are tagged by diversity family for analysis.

Technical approach:
- Expand open-ended template bank in `src/andromeda/eval/generation.py` with broader families:
  - strategy/positioning
  - growth drivers vs risks
  - evidence-grounded definitions/explanations
  - period-over-period narrative synthesis
  - inference-style but filing-grounded causal reasoning
  - uncertainty/limitations framing
- Preserve deterministic sampling and no-template-repeat-until-exhaustion behavior.

files_to_change:
- `src/andromeda/eval/generation.py`

new_files:
- `agent_logs/20260217_*.sh` (dataset generation and open-ended eval scripts)

## Phase 2: Open-Ended Eval Harness Run (Iteration 1 Baseline on New Set)
Acceptance criteria:
- New open-ended-only dataset generated (`n=100`).
- Run generation+scoring completed with required timeout/threads.
- Metrics and run paths captured for iteration analysis.

Technical approach:
- Build a dedicated script to generate only open-ended questions from current profile.
- Run `scripts.run_eval` with open-ended-only filtering.
- Run `scripts.score_eval` with `judge-workers=12`, `judge-context-chars=80000`, retries enabled.

files_to_change:
- none (runtime scripts in `agent_logs/`)

new_files:
- `agent_logs/20260217_*_generate_openended100_diverse.sh`
- `agent_logs/20260217_*_eval_openended100_iter1.sh`

## Phase 3: Failure Analysis + Strategy Selection per Iteration
Acceptance criteria:
- Each iteration includes:
  - failure slice inspection
  - at least 3 broad candidate strategies
  - explicit selected strategy with reasoning
  - one implemented change
  - rerun + metric comparison vs prior iteration
- LOGBOOK updated at end of each iteration.

Technical approach:
- Analyze `review.csv`/`cases.jsonl` on failed faithfulness rows.
- Track error modes (e.g., unsupported generalizations, period conflation, quote/claim mismatch, distractor leakage).
- Prioritize generalizable prompt/methodology improvements over dataset-specific hacks.

files_to_change (iteration-dependent):
- likely `src/andromeda/qa.py`
- likely `src/andromeda/query_runtime.py`
- possibly `scripts/score_eval.py` (analysis instrumentation only if needed)

new_files:
- `agent_logs/20260217_*_analyze_openended_failures.py` (if needed)
- per-iteration run scripts in `agent_logs/`

## Phase 4: Logging + Reproducibility Discipline
Acceptance criteria:
- LOGBOOK appended after every iteration with:
  - what changed
  - metrics observed
  - surprises/lessons
  - strategy proposals considered
  - chosen strategy and why
  - next actionable steps
  - commit hash references

Technical approach:
- Commit once per iteration (or more if naturally split), then append LOGBOOK immediately.
- Keep all custom run/analysis scripts in `agent_logs/`.

files_to_change:
- `agent_logs/LOGBOOK.md`

new_files:
- iteration scripts/log artifacts under `agent_logs/`

## Suggestions (future, not in current scope)
- Add claim-level faithfulness audit (claim extraction + verification) for richer diagnostics.
- Add pairwise helpfulness judge harness for A/B comparison between iteration outputs on fixed generations.
