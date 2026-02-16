# Plan: Re-add On-the-Fly Ticker Ingestion (14Feb2026 20:25:05)

## Context
- Referenced `agent_logs/LOGBOOK.md` before planning to align with existing PostgreSQL-first architecture, sparse-method compatibility checks, and TS modular UI patterns.
- Goal: replace disabled upload/OCR ingestion with ticker-only background ingestion (`download -> process_html_to_markdown -> chunk -> build_index`) while preserving active runtime PostgreSQL/schema retrieval settings.

## Technical approach
- Add a dedicated backend ingestion job module that:
  - accepts `(ticker, per_company)` only,
  - runs the pipeline asynchronously in a background thread,
  - tracks job lifecycle/status,
  - builds `scripts.build_index` args from current runtime env so schema/sparse/context/embedding configuration is aligned with active app settings.
- Replace `/ingest` API contract to JSON ticker ingestion and add a status endpoint for polling.
- Add a small UI control block for triggering ingestion + polling status.
- Add tests for API behavior and command-arg compatibility logic.

## Phase 1: Backend ingestion job orchestration
### Scope
- Implement `src/andromeda/ingestion_jobs.py` with:
  - typed runtime config model,
  - command builders for each pipeline step,
  - threaded job manager + status snapshots,
  - subprocess runner with per-job logs.
- Wire into `src/andromeda/main.py`:
  - new request/response models for ticker ingestion,
  - `POST /ingest` (ticker + per_company only),
  - `GET /ingest/{job_id}` for status.
- Remove upload/OCR endpoint contract and unused request types/imports.

### Acceptance criteria
- API rejects non-ticker ingestion payloads and no longer accepts file uploads/OCR flags.
- `POST /ingest` returns a job id immediately.
- `GET /ingest/{job_id}` returns lifecycle state (`queued/running/succeeded/failed`) and stage/message.
- Build-index command includes active runtime DB/schema/sparse/context/embedding settings.

## Phase 2: Frontend ingestion controls
### Scope
- Update `src/andromeda/static/index.html` with a compact ticker ingestion section.
- Extend `src/andromeda/static/ts/index/dom.ts` and `src/andromeda/static/ts/index/main.ts`:
  - submit ticker/per-company,
  - poll job status,
  - reflect status in UI,
  - refresh ingested companies panel on success.
- Rebuild compiled JS assets from TS.

### Acceptance criteria
- User can submit ticker + per-company from UI.
- UI displays job progress/status and terminal outcome.
- On successful completion, ingested company panel reload is triggered.

## Phase 3: Tests, docs, and logs
### Scope
- Add/adjust tests:
  - backend API tests for ingestion endpoints,
  - unit tests for build-index command argument parity.
  - UI e2e smoke for ingestion controls/status.
- Update `CHANGELOG.md` for behavior change.
- Append implementation notes/learning/results to `agent_logs/LOGBOOK.md`.
- Preserve executed validation script(s) under `agent_logs/` and run required checks.

### Acceptance criteria
- `pre-commit run --all` passes.
- `pytest -vvv tests/` passes.
- New tests cover ticker-only ingestion API + runtime-arg compatibility path.

## files_to_change
- `src/andromeda/main.py`
- `src/andromeda/static/index.html`
- `src/andromeda/static/ts/index/dom.ts`
- `src/andromeda/static/ts/index/main.ts`
- `src/andromeda/static/js/index/dom.js` (generated)
- `src/andromeda/static/js/index/main.js` (generated)
- `tests/test_main_api_e2e.py`
- `tests/ui/index.spec.ts`
- `CHANGELOG.md`
- `agent_logs/LOGBOOK.md`

## new_files
- `src/andromeda/ingestion_jobs.py`
- `tests/test_ingestion_jobs.py`
- `agent_logs/ticker_ingestion_14Feb2026_202505.md`
- `agent_logs/validate_ticker_ingestion_14Feb2026_*.sh`

## Future add-ons (not in current scope)
- Persist job history in PostgreSQL (survives process restart).
- Add cancellation endpoint for active ingestion jobs.
- Add richer per-step metrics (counts, durations) in the status payload.
