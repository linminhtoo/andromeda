# Query Pipeline Dedup Plan (2026-02-15 00:52:23)

## Context
- `src/finrag/main.py` has duplicated retrieval/rerank and answer-generation branching between `RAGService.answer_question()` and `/query_stream`.
- Upcoming answer-logic branches would require touching both code paths, increasing regression risk.
- Reviewed `agent_logs/LOGBOOK.md` to align with prior refactor and validation practices.

## Phase 1: Extract shared query pipeline helpers
- **files_to_change**: `src/finrag/main.py`
- **new_files**: none
- **Approach**:
  - Add focused `RAGService` helpers for retrieval filters, retrieval, rerank, prompt construction, and final response assembly.
  - Move `answer_question()` to call the shared helpers only.
- **Acceptance criteria**:
  - `answer_question()` no longer contains direct retrieval/rerank branching logic duplication.
  - Existing response shape (`QueryResponse`) is unchanged.

## Phase 2: Rewire streaming endpoint to use shared helpers
- **files_to_change**: `src/finrag/main.py`
- **new_files**: none
- **Approach**:
  - Replace direct retriever/reranker calls in `/query_stream` with the new `RAGService` helpers.
  - Introduce one local streaming-stage helper to remove repeated delta batching loops for draft/final stages.
  - Keep event contract and cancellation behavior intact.
- **Acceptance criteria**:
  - Shared RAG pipeline helpers are used by both synchronous and streaming query flows.
  - Streaming NDJSON event types remain compatible with current frontend behavior.

## Phase 3: Validate and document
- **files_to_change**: `CHANGELOG.md`, `agent_logs/LOGBOOK.md`, `agent_logs/20260215_validate_query_pipeline_dedup.sh`
- **new_files**: `agent_logs/20260215_validate_query_pipeline_dedup.sh`
- **Approach**:
  - Run required checks: `source .venv/bin/activate && pre-commit run --all`, then `pytest -vvv tests/`.
  - Record results/observations in `LOGBOOK.md`.
  - Update changelog with maintainability refactor summary.
- **Acceptance criteria**:
  - Lint/format/type checks and tests pass, or failures are documented with rationale.
  - Logbook/changelog capture the behavioral impact and validation outcome.

## Suggested follow-ups (out of current scope)
- Add explicit unit tests around shared RAG helper methods to lock event/branch behavior.
- Consider extracting streaming orchestration into a dedicated module if `main.py` keeps growing.
