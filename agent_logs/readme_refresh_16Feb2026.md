# README rewrite plan (16 Feb 2026)

## Goal
Rewrite `README.md` as a professional, interview-ready technical document that reflects the current architecture (including tools-first query orchestration), while removing obsolete rewrite-process narrative.

## Scope
- In scope:
  - Re-scan current implementation and docs to align README with shipped behavior.
  - Rewrite README structure/content for technical clarity and professionalism.
  - Keep claims implementation-backed (code/tests/changelog/logbook).
- Out of scope:
  - Any runtime behavior change.
  - Any API/schema changes.

## files_to_change
- `README.md`
- `agent_logs/LOGBOOK.md`

## new_files
- `agent_logs/readme_refresh_16Feb2026.md`

## Technical approach
### Phase 1 - Source-of-truth synthesis (independently testable)
- Derive architecture and behavior facts from:
  - `src/finrag/main.py`, `src/finrag/query_runtime.py`, `src/finrag/query_streaming.py`
  - `src/finrag/finance_tools.py`, `src/finrag/runtime_builders.py`
  - `src/finrag/db.py`, `src/finrag/retriever.py`
  - `scripts/*.sh`, relevant tests, `CHANGELOG.md`, `agent_logs/LOGBOOK.md`
- Acceptance criteria:
  - Key sections and claims mapped to current code paths.

### Phase 2 - README redesign and rewrite (independently testable)
- Replace current rewrite-focused narrative with design-doc style structure:
  - System overview and product intent
  - End-to-end architecture (tools-first + RAG)
  - Query lifecycle and planner/tool semantics
  - Data model and retrieval strategy
  - Ingestion/indexing pipeline and profile-scoped storage
  - API endpoints and streaming event contract
  - Configuration and local runbook
  - Testing/quality gates
- Acceptance criteria:
  - README is coherent, concise, and accurate for technical interviews.
  - No obsolete migration-only framing remains.

### Phase 3 - Validation and handoff (independently testable)
- Run required checks:
  - `source .venv/bin/activate && pre-commit run --all`
  - `source .venv/bin/activate && pytest -vvv tests/`
- Append concise task notes in `agent_logs/LOGBOOK.md`.
- Acceptance criteria:
  - Lint/type/test checks complete and reported.
  - LOGBOOK updated with what changed and why.

## Potential future add-ons (not in current scope)
- Add architecture diagrams (sequence + component) generated from source contracts.
- Add benchmark/latency table from reproducible eval runs.
- Add deployment runbooks for production environments.
