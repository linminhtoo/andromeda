# Plan: Durable Ingest Profiles + Multi-Ticker Frontend Ingestion (14Feb2026 20:49:46)

## Context
- Re-read `agent_logs/LOGBOOK.md` and current ingestion wiring.
- User concerns are valid:
  - `build_index.sh` still hardcodes `--context neighbors --context-window 1`.
  - chunk settings (`--max-tokens`, `--overlap-tokens`) were not loaded into app-driven ingestion jobs.
  - relying only on current env vars is brittle and can drift from original index settings.

## Technical approach
- Introduce a persistent ingest profile store on disk keyed by profile name (defaulting to schema) that records step settings for:
  - download
  - process_html_to_markdown
  - chunk
  - build_index
- Make scripts update the profile after each run with the actual args used.
- Make app ingestion jobs load profile settings first (fallback to env defaults only when missing), including chunk and index settings.
- Add multi-ticker ingestion support through API + frontend.

## Phase 1: Durable profile store + script integration
### Scope
- Add `src/andromeda/ingest_profile.py` with read/write helpers and profile-name resolution.
- Update scripts to persist step settings:
  - `scripts/download.py`
  - `scripts/process_html_to_markdown.py`
  - `scripts/chunk.py`
  - `scripts/build_index.py`
- Update shell wrappers to stop hardcoding context/chunk args and accept env-driven values:
  - `scripts/build_index.sh`
  - `scripts/chunk.sh`

### Acceptance criteria
- Running each step writes/updates a profile JSON under profile directory.
- `build_index.sh` context args are sourced from env vars (with defaults), not hardcoded literals.
- `chunk.sh` max/overlap are sourced from env vars (with defaults), not hardcoded literals.

## Phase 2: App ingestion uses stored profile + supports multi-ticker
### Scope
- Extend ingestion runtime config/model to include chunk/process/index settings loaded from profile.
- Update `src/andromeda/main.py` ingestion config builder to prioritize profile settings, then fallback env defaults.
- Update ingestion job manager to accept multiple tickers per job.
- Update ingestion API request model to accept multi-ticker payloads.

### Acceptance criteria
- App ingestion command generation includes chunk max/overlap from profile when present.
- App can start one job for multiple tickers.
- Existing single-ticker use still works (backward compatible request shape).

## Phase 3: Frontend + tests + docs/logs
### Scope
- Update frontend ingest controls for multi-ticker input.
- Update API/unit/UI tests for profile loading and multi-ticker ingestion.
- Update `CHANGELOG.md` and append findings to `agent_logs/LOGBOOK.md`.
- Preserve a validation script under `agent_logs/` and run required checks.

### Acceptance criteria
- Frontend can submit multiple tickers in one ingestion request.
- New tests cover:
  - profile-backed command generation
  - multi-ticker API payloads
  - ingestion UI multi-ticker flow
- `pre-commit run --all` passes.
- `pytest -vvv tests/` passes.

## files_to_change
- `src/andromeda/main.py`
- `src/andromeda/ingestion_jobs.py`
- `scripts/build_index.sh`
- `scripts/chunk.sh`
- `scripts/download.py`
- `scripts/process_html_to_markdown.py`
- `scripts/chunk.py`
- `scripts/build_index.py`
- `src/andromeda/static/index.html`
- `src/andromeda/static/ts/index/dom.ts`
- `src/andromeda/static/ts/index/main.ts`
- `tests/test_ingestion_jobs.py`
- `tests/test_main_api_e2e.py`
- `tests/ui/index.spec.ts`
- `CHANGELOG.md`
- `agent_logs/LOGBOOK.md`

## new_files
- `src/andromeda/ingest_profile.py`
- `agent_logs/ingest_profiles_and_multi_ticker_14Feb2026_204946.md`
- `agent_logs/validate_ingest_profiles_multi_ticker_14Feb2026_*.sh`

## Future add-ons (not in current scope)
- Add a dedicated UI to browse/select profiles and inspect step-history diffs.
- Persist ingestion job history in DB for restart-safe monitoring.
