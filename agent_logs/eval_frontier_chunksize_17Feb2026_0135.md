# Eval Frontier Plan - Chunk Size Tradeoff + Expanded Iterations (17Feb2026 01:35)

## Objective
Map and improve eval behavior in a reproducible, commit-addressable way.

## Phase 1 - Chunk Size Tradeoff Study (run)

### Scope
Compare chunk sizes `256`, `512`, `1024` (current), `2048` on the same benchmark eval set and runtime settings.

### Technical approach
1. Reuse existing markdown corpus from profile `eval_revamp_20260216`.
2. Generate four chunk exports with same chunker and proportional overlap (`size/8`):
   - `chunked_256_32`, `chunked_512_64`, `chunked_1024_128`, `chunked_2048_256`.
3. Build four postgres indexes/schemas with `context=none`, `bm25`, same embedding model.
4. Run eval generation+scoring on the same query set for each schema/chunk directory:
   - benchmark query set: `eval/eval_queries_revamp_single_balanced_validated_tol05_20260216.jsonl`
   - mode `normal`, refine off, thread backend, fixed concurrency.
5. Aggregate latency + quality metrics into CSV/JSON and render a simple figure/table.

### Acceptance criteria
- All 4 chunk sizes have completed generation+score artifacts.
- A single comparison report exists with side-by-side metrics and latency.
- Results are documented in `LOGBOOK.md`.

### files_to_change
- `agent_logs/LOGBOOK.md`
- `CHANGELOG.md` (if behavior/tooling additions are introduced)

### new_files
- `agent_logs/<timestamp>_chunk_size_tradeoff_eval.sh`
- `agent_logs/<timestamp>_collect_chunk_size_metrics.py`
- `eval/results_revamp/chunk_size_study/*` (csv/json/figure/md)
- `agent_logs/chunk_size_tradeoff_17Feb2026.md`

## Phase 2 - Frontier Variables Map (write only, no runs)

### Scope
Enumerate additional controlled knobs for future tradeoff studies (quality/latency/cost frontier).

### Technical approach
- Produce an organized matrix: variable, expected effect, measurement protocol, risks, and suggested priority.

### Acceptance criteria
- One structured markdown file with clear experiment designs and no executed runs.

### files_to_change
- `agent_logs/LOGBOOK.md`

### new_files
- `agent_logs/eval_frontier_variables_17Feb2026.md`

## Phase 3 - Expanded Eval Optimization Iterations (run)

### Scope
Increase eval size to 100 with 12 generation workers; iterate to improve weak metrics while protecting already-strong categories.

### Technical approach
1. Build expanded single-ticker eval set (`n=100`) with wider ticker/query diversity.
2. Establish baseline run on expanded set (12 threads).
3. Iterate improvements with emphasis on weaker metrics (likely open-ended faithfulness/factual correctness calibration).
4. After **every** iteration:
   - commit code changes,
   - record commit hash,
   - append LOGBOOK entry with metrics + script path + commit hash.

### Acceptance criteria
- Expanded eval dataset artifact exists and is versioned.
- At least one completed optimization iteration beyond baseline is run/scored.
- Each iteration has a unique commit hash explicitly logged in `LOGBOOK.md`.

### files_to_change
- `src/andromeda/*` (as needed for prompt/harness/runtime tuning)
- `scripts/*` (as needed for eval harness)
- `tests/*` (if behavior changes)
- `agent_logs/LOGBOOK.md`
- `CHANGELOG.md` (if behavior changes)

### new_files
- `agent_logs/<timestamp>_generate_eval_set_expanded100.sh`
- `agent_logs/<timestamp>_run_eval_iteration_<id>.sh`
- `eval/eval_queries_revamp_single_expanded100_*.jsonl`

## Suggestions / Future work (not in this scope)
- Add automated commit-hash injection into run metadata JSON for exact provenance.
- Add bootstrap confidence intervals for judge fail-rate comparisons.
- Add cost-per-run accounting (tokens + wall time + API calls) in dashboard.
