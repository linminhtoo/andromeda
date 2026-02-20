# Plan 19Feb2026: Explain Retrieval Evaluation

## Objective
Document how retrieval evaluations work in the repo by tracing datasets, ground truths, and evaluation metrics.

## Files to Change
- None (informational task).
- New file: `agent_logs/plans/19Feb2026_retrieval_eval_explained.md` (this plan).

## Phases
1. **Survey evaluation assets**
   * Acceptance: Identify schema files and dataset loaders, note key directories/scripts.
   * Work: inspect `eval/*`, `src`, `scripts`, documentation (README_EVAL, BENCHMARK_RETRIEVAL), and relevant tests/logs.
2. **Document ground truth & metrics**
   * Acceptance: Trace how gold data is generated (scripts, heuristics, human/LLM labeling) and pinpoint evaluation entrypoints and metric calculations.
   * Work: inspect evaluation scripts (likely under `src/eval`, `eval`, `tests`), highlight main classes/functions.

## Potential Add-ons (Not this scope)
1. Generate diagram of data flow between dataset, retriever, evaluator.
2. Extract evaluation-cli options for future automation.
