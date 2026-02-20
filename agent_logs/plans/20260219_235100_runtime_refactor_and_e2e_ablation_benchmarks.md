# Runtime Refactor + E2E Ablation Benchmarks (2026-02-19)

## Scope
1. Remove `_enforce_ticker_coverage()` heuristic path and simplify multi-ticker rerank behavior.
2. Make the "at most 6 material points" prompt rule toggleable.
3. Commit the current full git tree (excluding `resume_proposal.tex`) in right-sized commits.
4. Run judged e2e eval baselines + ablations:
   - baseline (current best)
   - reranker disabled
   - material-points cap toggle ablation

## Phase 1: Runtime simplification
Acceptance criteria:
- `_enforce_ticker_coverage()` removed.
- `rerank_chunks_for_plan()` no longer applies ticker-coverage heuristic.
- Multi-ticker behavior remains functional and traceable via tool trace.

files_to_change:
- `src/andromeda/query/runtime.py`

new_files:
- none

## Phase 2: Prompt toggle
Acceptance criteria:
- material-points cap is configurable via environment variable.
- default behavior matches current production behavior.
- disabling cap removes the hard ceiling instruction.

files_to_change:
- `src/andromeda/query/runtime.py`
- optional docs if needed (`README_EVAL.md` or benchmark notes)

new_files:
- none

## Phase 3: Commit current tree
Acceptance criteria:
- all current tracked/untracked changes committed except `resume_proposal.tex`.
- commits are scoped and readable.

files_to_change:
- entire working tree except excluded file

new_files:
- none

## Phase 4: E2E judged ablations
Acceptance criteria:
- three runs executed and scored with judge pipeline under latest full-eval settings.
- results summarized with metric deltas and run dirs.

files_to_change:
- benchmark report markdown (`BENCHMARK*.md`)
- `agent_logs/LOGBOOK.md`

new_files:
- run artifacts under `eval/results_revamp/full_suite/`
- optional benchmark helper scripts under `agent_logs/scripts/`
