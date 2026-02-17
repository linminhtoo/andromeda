# Plan: Latency-Performance Frontier + Product Improvements (2026-02-18)

## Scope
Execute a deploy-matched benchmark campaign to map latency-performance tradeoffs, then implement product-facing improvements prioritized from `FUTURE_WORKS.md` with reproducible lineage.

## Constraints
- Keep eval settings deploy-matched (judge context 80k; no chunk/context text truncation hacks).
- Keep finance tools enabled for holistic behavior unless an experiment explicitly isolates a component.
- Commit after each major step.
- Preserve reproducibility (scripts + manifests + LOGBOOK entries).

## Phase 1: Complete chunk-size ablation rerun (fixed settings)
### Technical approach
- Let the active script finish all chunk sizes: `256/512/1024/2048` with overlap `1/8`.
- Use expanded eval sets (`single=100`, `multi=60`) and judge context `80,000`.
- Collect metrics into normalized report artifacts.

### Acceptance criteria
- `run_manifest_expanded80k.csv` contains all 4 chunk sizes.
- Each size has scored single + multi run directories.
- Aggregated output exists (`csv/json/md/png`) and supports latency + quality comparison.

### files_to_change
- `agent_logs/scripts/eval/20260218_060200_rerun_chunk_size_ablation_expanded80k.sh`
- `agent_logs/scripts/eval/20260218_053900_collect_chunk_size_ablation_expanded80k.py`
- `agent_logs/LOGBOOK.md`
- `CHANGELOG.md`

### new_files
- `eval/results_revamp/chunk_size_study_v2_expanded80k/*` (artifacts)
- `agent_logs/scripts/eval/*chunk_size*` (if script deltas needed)

## Phase 2: Latency-performance frontier mapping (multi-axis)
### Technical approach
- Run a controlled frontier harness on deploy-matched base index (chunk size 512).
- Axes: answering effort, retrieval depth, generation budget, decoding behavior.
- Keep judge/scoring settings fixed so comparisons are attributable to generation knobs.
- Produce consolidated metrics and simple visuals.

### Acceptance criteria
- Manifest and metrics table for all configured experiments.
- Pareto-style interpretation in markdown report (speed vs fail-rate changes).
- Scripted, reproducible rerun command in docs.

### files_to_change
- `agent_logs/scripts/eval/20260218_060600_run_latency_accuracy_frontier.sh`
- `agent_logs/scripts/eval/20260218_060700_collect_latency_accuracy_frontier.py`
- `agent_logs/reports/latency_performance_frontier_priorities_20260218.md`
- `agent_logs/LOGBOOK.md`

### new_files
- `eval/results_revamp/latency_accuracy_frontier_20260218/*`

## Phase 3: Implement top product improvements from roadmap
### Technical approach
- Prioritize customer-facing reliability + speed with minimal overfitting:
  1. Adaptive retrieval budget scheduler (question complexity-aware k settings).
  2. Explicit tool-first numeric policy tracing (clear fallback reason telemetry).
  3. Optional prompt-prefix stabilization hooks for cacheability (no behavior regression).
- Measure impact on targeted slices (numeric/factual + open-ended faithfulness/helpfulness).

### Acceptance criteria
- Code paths are configurable and deploy-safe.
- At least one measurable improvement dimension reported (quality, latency, or stability).
- No regressions in already-strong metrics beyond agreed tolerance.

### files_to_change
- `src/andromeda/query/runtime.py`
- `src/andromeda/llm/generation_controls.py`
- `src/andromeda/eval/runner.py`
- `scripts/run_eval.py`
- `README_EVAL.md`
- `README.md`
- `agent_logs/LOGBOOK.md`
- `CHANGELOG.md`

### new_files
- `agent_logs/scripts/eval/*frontier*` (if additional targeted harness scripts needed)
- `agent_logs/reports/*frontier*` (analysis output)

## Phase 4: Documentation + reproducibility hardening
### Technical approach
- Update eval and repo docs to reflect current best settings and one-pass full-suite execution.
- Ensure moved `agent_logs` paths are correct and consistent.
- Record commit hashes + exact commands + observations for every iteration.

### Acceptance criteria
- README docs provide a clean single-pass reproducible flow.
- LOGBOOK entries reference commit hashes and summarize outcomes per iteration.
- Changelog captures user-visible behavior changes.

### files_to_change
- `README_EVAL.md`
- `README.md`
- `agent_logs/LOGBOOK.md`
- `CHANGELOG.md`

### new_files
- None required beyond generated reports.

## Suggested follow-on ideas (not in current scope)
- Bootstrap confidence intervals integrated directly into score summaries.
- Automated judge calibration dashboards with manual-label disagreement strata.
- Cost-aware scheduler balancing latency SLO and token budget per query family.
