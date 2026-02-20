# 20260218 Reduced-Heuristics Eval + Retrieval Benchmark Plan

## Scope
Complete three deliverables on branch `mlin/reduce-hardcoded-heuristics`:
1) checkpoint right-sized commits without undoing any existing changes,
2) re-run eval pipeline on current best defaults and produce a detailed reduced-heuristics benchmark report,
3) implement `IMPROVE_RAG_EVAL.md` recommendations and produce a retrieval/reranking quality benchmark report.

## Phase 1 - Commit checkpoint hygiene

### Approach
- Review current modified/untracked files and group them into coherent commit units.
- Keep unrelated user-provided files intact; do not discard or rewrite externally-added content.
- Commit runtime + tests + docs as separate logical slices where possible.

### Acceptance criteria
- Working tree is checkpointed with traceable commits before new experiments start.
- No existing changes are undone.

## Phase 2 - Reduced-heuristics eval rerun + judge alignment audit

### Approach
- Identify and use the best-current eval settings (from README/BENCHMARK and code defaults).
- Run full eval pipeline with current defaults and capture run artifact paths.
- Perform manual audit on both judge-failure and judge-pass samples to estimate alignment quality.
- Compare new metrics versus benchmark history (prioritizing comparable non-heuristic-heavy baselines).
- Write `BENCHMARK_REDUCED_HEURISTICS.md` with metrics, failure patterns, surprises, and hypotheses.

### Acceptance criteria
- Reproducible run command(s) and run IDs are documented.
- Manual audit includes both positive and negative judge decisions.
- Report clearly contrasts current run against prior benchmark records.

## Phase 3 - Implement `IMPROVE_RAG_EVAL.md` recommendations

### Approach
- Read and translate recommendations into concrete code/task changes.
- Add retrieval/rerank evaluation support and local benchmark harness updates.
- Evaluate open-source local models for retrieval/reranking analysis; prefer credible finance-capable models when available.
- Use model-assisted audit to approximate expert chunk relevance checks and summarize confidence/limitations.

### Acceptance criteria
- Recommendations are implemented or explicitly documented as blocked/deferred with rationale.
- Retrieval/reranking benchmark output is generated and reproducible.

## Phase 4 - Retrieval/reranking benchmark report

### Approach
- Run retrieval/rerank benchmarks with updated harness.
- Analyze chunk relevance quality and reranker lift with model-assisted audits.
- Write `BENCHMARK_RETRIEVAL.md` with findings, surprises, and hypotheses.

### Acceptance criteria
- Report includes methods, datasets, metrics, key error modes, and improvement hypotheses.
- Report includes enough detail for interview/demo discussion.

## Phase 5 - Logging, validation, and final cleanup

### Approach
- Append LOGBOOK entries after each major iteration/commit with commit hashes.
- Update CHANGELOG for behavior changes.
- Run final repo checks (`pre-commit run --all`, `pytest -vvv tests/`).

### Acceptance criteria
- LOGBOOK provides traceable lineage with commit references.
- Lint/tests pass at wrap-up.

## files_to_change
- `BENCHMARK_REDUCED_HEURISTICS.md` (new)
- `BENCHMARK_RETRIEVAL.md` (new)
- `agent_logs/LOGBOOK.md`
- `CHANGELOG.md`
- `src/andromeda/query/runtime.py`
- `src/andromeda/query/planner_heuristics.py`
- `tests/test_query_runtime_tools_first.py`
- eval/retrieval benchmark scripts and related source files as required by recommendations in `IMPROVE_RAG_EVAL.md`

## new_files
- `agent_logs/plans/20260218_reduced_heuristics_eval_and_retrieval_bench.md`
- `BENCHMARK_REDUCED_HEURISTICS.md`
- `BENCHMARK_RETRIEVAL.md`
- Additional benchmark helper scripts under `agent_logs/scripts/` as needed

## Suggested future work (out of current scope)
- Add dedicated paid-LLM integration test suite with environment-gated execution in CI/nightly.
- Add lightweight human-labeled retrieval relevance set for calibration of model-assisted audits.
