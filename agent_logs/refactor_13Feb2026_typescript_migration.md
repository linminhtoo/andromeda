# TypeScript Migration Plan (2026-02-13)

## Goal
Migrate frontend runtime code from inline JavaScript to TypeScript for both web UIs (`/` and `/review`), keep behavior parity, and ensure the launched app serves and executes compiled frontend assets.

## Scope
- Migrate **all inline frontend script logic** in:
  - `src/finrag/static/index.html`
  - `src/finrag/static/review.html`
- Add TypeScript tooling/config.
- Compile TS to JavaScript artifacts used by the running FastAPI apps.
- Wire static serving for compiled JS for both:
  - `finrag.main:app`
  - `finrag.review_app:app`
- Update docs/changelog for TS build/runtime workflow changes.

## Files

### files_to_change
- `src/finrag/main.py`
- `src/finrag/review_app.py`
- `src/finrag/static/index.html`
- `src/finrag/static/review.html`
- `scripts/launch_app.sh`
- `scripts/launch_review.sh`
- `README.md`
- `CHANGELOG.md`
- `experiments/LOGBOOK.md`

### new_files
- `package.json`
- `tsconfig.json`
- `src/finrag/static/ts/index/` (module tree, entrypoint `main.ts`)
- `src/finrag/static/ts/review/` (module tree, entrypoint `main.ts`)
- `src/finrag/static/ts/shared/`
- `experiments/20260213_validate_typescript_migration.sh`

## Technical approach
1. Extract each inline `<script>` block into TypeScript source files.
2. Add a conservative TS config (DOM libs, relaxed strictness for large legacy script migration) to preserve runtime behavior while introducing typed compilation.
3. Compile TS output directly into `src/finrag/static/` (`index.js`, `review.js`) so FastAPI can serve stable assets without introducing a bundler.
4. Replace inline scripts in HTML with external script references to compiled files.
5. Mount `/static` in both app entrypoints so compiled JS is resolvable in both launch modes.
6. Update launch scripts to compile TypeScript before starting the server.
7. Run validation:
   - TS compile
   - app launch smoke checks for `/`, `/review`, and script references
   - repo lint/test commands per project policy

## Phases and acceptance criteria

### Phase 1: Tooling and wiring
- Add `package.json` + `tsconfig.json`.
- Add `/static` serving for both FastAPI apps.
- Acceptance: `npm run build:ts` emits JS assets and both apps can serve `/static/index.js` + `/static/review.js`.

### Phase 2: Script migration
- Move inline JS from both HTML files to TS files.
- Replace inline script tags with external script tags.
- Acceptance: pages still load, with no missing-element or syntax/runtime startup errors in smoke checks.

### Phase 3: Docs and verification
- Update README and CHANGELOG with TS workflow and migration note.
- Run formatting/lint/tests per repo rules and log outcomes.
- Record results in `experiments/LOGBOOK.md`.
- Acceptance: commands complete (or failures documented with reasons and impact).

## Risks
- Large inline scripts may rely on implicit global browser behavior.
- TypeScript compile may surface DOM/nullability friction; use targeted typing shims, not behavior changes.
- Runtime can break if `/static` is not mounted in both app entrypoints.

## Future work (not in this scope)
- Raise TS strictness incrementally (`strict`, `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`).
- Split monolithic TS files into modules by feature area.
- Add frontend unit tests and CI checks for TS build + browser smoke tests.
