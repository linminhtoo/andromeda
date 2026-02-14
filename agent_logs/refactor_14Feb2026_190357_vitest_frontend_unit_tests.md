# Vitest frontend unit-test layer plan (2026-02-14 19:03:57)

## Scope
Add fast unit tests for pure frontend helper logic while keeping existing Playwright browser-flow tests for integration behavior.

## Technical approach
1. Install/configure Vitest for TypeScript unit tests in a Node test environment.
2. Add focused unit coverage for:
   - `src/finrag/static/ts/index/markdown.ts`
   - `src/finrag/static/ts/index/citations.ts`
3. Keep Playwright tests as-is for browser interaction checks.
4. Add npm scripts and run full validation (`pre-commit`, Python tests, unit tests, Playwright tests).

## Phases

### Phase 1: Vitest setup
Acceptance criteria:
- `vitest` is installed and runnable.
- Project config supports TS unit tests.
- npm scripts exist for non-watch CI-style unit test execution.

files_to_change:
- `package.json`
- `package-lock.json`

new_files:
- `vitest.config.ts`

### Phase 2: Unit tests for markdown/citations helpers
Acceptance criteria:
- Unit tests cover markdown rendering branches including headings, links, lists, tables, fenced code, and thematic breaks.
- Unit tests cover citation labeling, target registration, chunk/doc lookup precedence, marker parsing, and HTML output attributes.
- Tests are deterministic and do not rely on browser or backend services.

files_to_change:
- none

new_files:
- `tests/ui-unit/markdown.spec.ts`
- `tests/ui-unit/citations.spec.ts`

### Phase 3: Validation + docs/logging
Acceptance criteria:
- `npm run -s test:unit` passes.
- Existing Playwright tests still pass.
- `source .venv/bin/activate && pre-commit run --all` passes.
- `source .venv/bin/activate && pytest -vvv tests/` passes.
- `CHANGELOG.md` and `agent_logs/LOGBOOK.md` updated with concise notes.
- Repro script saved under `agent_logs/`.

files_to_change:
- `CHANGELOG.md`
- `agent_logs/LOGBOOK.md`

new_files:
- `agent_logs/20260214_validate_vitest_frontend_unit_tests.sh`

## Risks and mitigations
- ESM import paths in TS source use `.js` suffixes.
  - Mitigation: run Vitest in Vite-compatible TS mode and verify module resolution with real imports.
- Over-testing renderer internals can create brittle tests.
  - Mitigation: assert stable HTML outcomes for representative inputs, not private implementation details.

## Suggestions for future work (not in current scope)
- Add coverage thresholds for `tests/ui-unit/**` once test set stabilizes.
- Add a compact CI job splitting fast unit tests and slower Playwright tests into separate stages.
