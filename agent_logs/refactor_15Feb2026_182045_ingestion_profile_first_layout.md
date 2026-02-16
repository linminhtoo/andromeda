# Ingestion Profile First Layout Refactor (15 Feb 2026 18:20:45 UTC)

## Goal
Make ingestion artifacts and PostgreSQL schema explicitly bound to a single ingestion profile so each experiment/profile produces isolated filesystem outputs and schema state by default.

## Technical approach
1. Add a shared ingest-profile layout resolver in `src/andromeda/ingest_profile.py`.
2. Use the resolver in `scripts/download.py`, `scripts/process_html_to_markdown.py`, `scripts/chunk.py`, and `scripts/build_index.py` to auto-derive profile-scoped default paths/schema when explicit CLI values are not provided.
3. Update shell wrappers in `scripts/*.sh` to default to profile-scoped paths instead of legacy flat directories.
4. Update runtime/orchestration (`src/andromeda/runtime_builders.py`, `src/andromeda/ingestion_jobs.py`) so profile and schema are consistently tied for on-the-fly ingestion.
5. Add/update tests for path and schema derivation behavior.
6. Document behavior change in `CHANGELOG.md` and append learnings to `agent_logs/LOGBOOK.md`.

## Phases

### Phase 1: Core profile layout resolver
- Scope: add deterministic helpers for profile root and step directories, plus default schema derivation tied to profile.
- Acceptance criteria:
  - Helpers return stable, profile-scoped paths under `data/ingest_profiles/<profile>/...`.
  - Helpers are usable by scripts without requiring env mutation.

### Phase 2: Script integration
- Scope: wire resolver into download/process/chunk/build_index argument resolution.
- Acceptance criteria:
  - Running each script with only `--ingest-profile` uses profile-scoped directories.
  - `build_index` defaults `--postgres-schema` to profile-derived schema when omitted.
  - Explicit CLI flags still override defaults.

### Phase 3: Runtime + orchestration alignment
- Scope: ensure on-the-fly pipeline uses profile-scoped locations and schema tied to profile.
- Acceptance criteria:
  - Runtime config resolves schema from profile when absent in profile step settings/env.
  - Ingestion job commands remain coherent with profile-first layout.

### Phase 4: Validation + docs
- Scope: tests + changelog + logbook + preserved validation script.
- Acceptance criteria:
  - `pre-commit run --all` passes.
  - `pytest -vvv tests/` passes.
  - CHANGELOG and LOGBOOK entries clearly state previous behavior and new behavior.

## files_to_change
- `src/andromeda/ingest_profile.py`
- `src/andromeda/runtime_builders.py`
- `scripts/download.py`
- `scripts/process_html_to_markdown.py`
- `scripts/chunk.py`
- `scripts/build_index.py`
- `scripts/download.sh`
- `scripts/process_html_to_markdown.sh`
- `scripts/chunk.sh`
- `scripts/build_index.sh`
- `tests/test_ingest_profile.py`
- `tests/test_ingestion_jobs.py` (if required by integration changes)
- `CHANGELOG.md`
- `agent_logs/LOGBOOK.md`

## new_files
- `agent_logs/refactor_15Feb2026_182045_ingestion_profile_first_layout.md`
- `agent_logs/20260215_182045_validate_ingestion_profile_first_layout.sh`

## Future add-ons (not in current scope)
- Add a CLI to clone/freeze profile versions and compute profile fingerprints.
- Add migration utility to move legacy flat data folders into profile-scoped layout.
- Add schema retention/garbage-collection tooling for old experiments.
