# 18Feb2026 Retrieval Metrics Plan

## Objective
Document the current eval retrieval/rerank observability and plan the implementation of
metrics for (a) pre-rerank retrieval coverage, (b) reranker uplift (gold evidence rank
differentials), and (c) claim–evidence support. The implementation must reuse the
existing metrics helpers, keep evaluations readable, and keep CLI outputs in sync.

## Phases
1. **Inventory & touchpoints**
   - Acceptance: Identify which files/functions already emit retrieval information (`EvalGeneration`,
     `score_one`, `summarize`, `scripts/score_eval.py`, `EvalScore.retrieval` dict, `EvalSummary`).
   - Document where `retrieved_chunks` vs `top_chunks` are populated so downstream scoring can observe
     pre-rerank data and citations.
2. **Extend scoring helpers**
   - Acceptance: `score_one` computes per-query metrics for retrieval recall/MRR, reranker uplift (rank delta for
     gold chunk/doc, recall jump), and claim-evidence coverage (citation counts and chunk coverage per claim) using
     helpers in `andromeda.eval.metrics` and `_cited_chunk_ids`.
   - Update `summarize` to surface aggregated uplift/coverage (e.g., mean rerank gain, claim citation rate). Add
     targeted unit tests for the new helpers (`tests/test_eval_schema_scoring.py` and/or a new metrics test).
3. **Surface & document results**
   - Acceptance: `scripts/score_eval.py` review CSV + cases now include the new metrics; generated `score_summary.json` and
     HTML report display pre-rerank vs rerank recall plus evidence support stats.
   - Note: Update `agent_logs/LOGBOOK.md` with a short entry describing the new metric coverage. Plan for `pre-commit run --all`
     and `pytest -vvv tests/` after the implementation.

## File-level edits
- `src/andromeda/eval/scoring.py` (score_one, helper functions, summary aggregation)
- `src/andromeda/eval/metrics.py` (add helpers for citation counts/rerank deltas if needed)
- `src/andromeda/eval/report.py` (display new metric cards/details)
- `scripts/score_eval.py` (add repo rows/columns for new metrics, keep cases consistent)
- `tests/test_eval_schema_scoring.py` (extend to cover the new metrics)
- Possibly `tests/test_eval_metrics.py` if new helpers live there.

## New files
- None planned yet. If new helper module is required for claim-evidence parsing, create e.g.
  `src/andromeda/eval/claim_support.py` and add to `files_to_change` above.

## Existing utilities to reuse
- `andromeda.eval.metrics.recall_at_k`, `mrr`, `coverage_at_k` for pre-rerank metric calculations.
- `_cited_chunk_ids` / `cited_doc_ids` (in `scoring.py` / `metrics.py`) for claim–evidence support.
- `EvalGeneration.retrieved_chunks` vs `top_chunks` as the data sources. `summarize()` already folds `score.retrieval` into
  `score_summary.json`.

## Potential add-ons / future work
- Add a CLI flag to `scripts/run_eval.py` / `score_eval.py` to emit per-stage recall CSVs.
- Hook new metrics into the HTML report generator for interactive exploration.
- Record a runnable script under `agent_logs/scripts/` if any bespoke data extraction is needed later.
