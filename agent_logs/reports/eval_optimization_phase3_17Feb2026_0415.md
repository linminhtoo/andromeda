# Phase 3 Plan: Expanded Eval (n=100) + Iterative Optimization

Date: 2026-02-17

## Goal
Continue deep-dive eval mapping on this branch by:
1. Building an expanded single-ticker eval dataset (n=100) with broader ticker coverage.
2. Running baseline + iterative improvements focused on reducing faithfulness failures without `--enable-refine`.
3. Committing after each iteration and logging commit hashes in `agent_logs/LOGBOOK.md`.

## Approach

### Phase A: Expanded Corpus + Eval Set (single-ticker)
- Create a combined chunk export from two existing 1024/128 corpora:
  - `eval_revamp_20260216` (large-cap tech set)
  - `exp__chunk_1024_o128_tokenizer__ctx_none__index_m24_ef200` (broader industrial/semicap set)
- Build a new postgres schema from the combined chunk export.
- Generate a new validated query pool (Edgar tol=0.5) and construct a balanced single-ticker subset of size 100.

Acceptance criteria:
- Combined corpus indexed successfully.
- New single-ticker eval file with exactly 100 rows exists.
- Query-set summary (kind mix + factual validation statuses) recorded in LOGBOOK.

### Phase B: Baseline + Diagnostics
- Run baseline generation on the new 100-query single-ticker set with:
  - mode `normal`
  - `concurrency=12`
  - no refine
  - finance tools enabled
  - larger timeout
- Score and produce dashboard row.
- Perform data-driven failure analysis by inspecting:
  - `review.csv`
  - selected `cases.jsonl`
  - tool trace/tool usage diagnostics (if available, or add instrumentation if missing).

Acceptance criteria:
- Baseline run + score artifacts produced.
- Faithfulness/factual failure clusters documented with concrete examples.

### Phase C: Iterative Improvements (single-ticker only)
- Prioritize:
  1) prompt-template improvements,
  2) retrieval/routing methodological improvements with low latency overhead,
  3) judge harness reliability fixes when metrics indicate judge-context issues.
- After every iteration:
  - run eval,
  - score,
  - update dashboard,
  - commit,
  - append LOGBOOK entry with commit hash and metric delta.

Acceptance criteria:
- At least one iteration with measurable faithfulness improvement vs baseline on eval100.
- All iteration commits and hashes are logged in LOGBOOK.

## Files To Change
- `src/andromeda/eval/schema.py` (if adding eval trace fields)
- `src/andromeda/eval/runner.py` (if persisting additional generation diagnostics)
- `src/andromeda/eval/judges.py` / `src/andromeda/eval/scoring.py` (if judge harness adjustments)
- `src/andromeda/qa.py` / `src/andromeda/query_runtime.py` (prompt/routing improvements)
- `scripts/eval_dashboard.py` (if dashboard aggregation needs new metrics)
- `agent_logs/LOGBOOK.md`
- `agent_logs/*` run scripts and analysis notes

## New Files
- `agent_logs/*` scripts for corpus merge, eval-set creation, and iteration runs
- `agent_logs/*` per-iteration analysis notes

## Suggestions (future, not in current scope)
- Add a judge timeout mechanism in `scripts/score_eval.py` to avoid indefinite tail hangs.
- Add automatic confidence intervals via bootstrap in dashboard output.
