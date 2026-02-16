# Rebrand Plan: `andromeda` -> `andromeda` (17 Feb 2026)

## Objective
Rename project/package references from `andromeda` to `andromeda` across source, tests, scripts, and key project metadata (including `pyproject.toml`) while keeping runtime behavior unchanged.

## Technical approach
1. Rename the Python package directory `src/andromeda` to `src/andromeda`.
2. Update import/module references (`andromeda...` -> `andromeda...`) in tracked code/docs/scripts.
3. Update key config paths and entrypoints in files like `pyproject.toml`, shell launch scripts, test config, and pre-commit settings.
4. Keep generated/runtime artifacts (`logs/`, `node_modules/`, `.venv/`) untouched.
5. Run formatting/linting and full test suite to validate stability.
6. Record behavior-impact notes in `CHANGELOG.md` and `agent_logs/LOGBOOK.md`.

## Phases

### Phase 1: Mechanical rename and path updates
Acceptance criteria:
- `src/andromeda` exists and `src/andromeda` no longer exists.
- Tracked source/test/script files no longer import `andromeda`.
- Key metadata/config files reference `andromeda`.

### Phase 2: Validation
Acceptance criteria:
- `source .venv/bin/activate && pre-commit run --all` passes.
- `source .venv/bin/activate && pytest -vvv tests/` passes.

### Phase 3: Documentation lineage
Acceptance criteria:
- `CHANGELOG.md` includes a note about the rename.
- `agent_logs/LOGBOOK.md` appended with scope, changes, and validation results.

## files_to_change
- `pyproject.toml`
- `.pre-commit-config.yaml`
- `.gitignore`
- `README.md`
- `README_EVAL.md`
- `CHANGELOG.md`
- `scripts/*` (where module path strings reference package name)
- `tests/*` (imports and path expectations)
- `agent_logs/LOGBOOK.md`
- all files under renamed package path (after move): `src/andromeda/**/*`

## new_files
- `agent_logs/rebrand_andromeda_to_andromeda_17Feb2026_015931.md`

## Potential future work (not in this scope)
- Migrate environment variable names prefixed with `FINRAG_` to `ANDROMEDA_` with backward-compatible aliases.
- Rename repository folder itself if desired.
