# Playwright setup + index UI refresh plan (2026-02-14 18:46:13)

## Scope
Improve `src/finrag/static/index.html` UX and interaction reliability while setting up Playwright-based UI interaction/testing.

## Technical approach
1. Introduce Playwright test runner/config for the frontend and add at least one deterministic UI test for citation-to-source navigation + markdown rendering behavior.
2. Fix citation click handling by supporting chunk-level citation targets in rendered answers (while keeping current doc-level fallback).
3. Reduce visual clutter by collapsing/hidden-by-default secondary panels (progress feed and draft tab) and tightening layout responsiveness.
4. Improve answer markdown rendering so thematic breaks (`---`) render correctly.
5. Validate with TS build/tests, Playwright run, pre-commit, and pytest.

## Phases

### Phase 1: Playwright setup
Acceptance criteria:
- `@playwright/test` is installed and runnable from npm scripts.
- A project config exists and can launch the local app for tests.
- A baseline UI test runs in Chromium headless and passes.

files_to_change:
- `package.json`
- `package-lock.json`

new_files:
- `playwright.config.ts`
- `tests/ui/index.spec.ts`

### Phase 2: Citation jump + markdown rendering fixes
Acceptance criteria:
- Citations encoded with `chunk=` jump directly to matching highlight in source viewer.
- Existing `doc=` citations still work as fallback.
- Markdown horizontal rules (`---`, `***`, `___`) render as `<hr>`.

files_to_change:
- `src/finrag/static/ts/index/citations.ts`
- `src/finrag/static/ts/index/main.ts`
- `src/finrag/static/ts/index/markdown.ts`

new_files:
- none

### Phase 3: UI density/responsiveness improvements
Acceptance criteria:
- Progress feed (detailed logs) is collapsed/hidden by default with clear toggle affordance.
- Draft answer panel is hidden by default and only shown when relevant.
- Main answer/source layout has cleaner spacing and improved responsiveness.
- No regressions in existing controls and interactions.

files_to_change:
- `src/finrag/static/index.html`
- `src/finrag/static/ts/index/dom.ts`
- `src/finrag/static/ts/index/main.ts`

new_files:
- none

### Phase 4: Build + quality validation + documentation
Acceptance criteria:
- TypeScript compiles to `src/finrag/static/js/**` without errors.
- Playwright tests pass.
- `pre-commit run --all` passes.
- `pytest -vvv tests/` passes.
- `CHANGELOG.md` and `agent_logs/LOGBOOK.md` updated with concise lineage notes.
- Repro/validation script saved under `agent_logs/`.

files_to_change:
- `src/finrag/static/js/index/*.js` (generated)
- `CHANGELOG.md`
- `agent_logs/LOGBOOK.md`

new_files:
- `agent_logs/20260214_validate_playwright_ui_refresh.sh`

## Risks and mitigations
- Streaming API and live backend state make E2E flaky.
  - Mitigation: use deterministic route mocking in Playwright tests for targeted UI behavior.
- Citation formats may vary (`doc=` only vs `doc=... chunk=...`).
  - Mitigation: parse both and prioritize chunk-level target when available.

## Suggestions for future work (not in current scope)
- Add a persistent user preference model for panel visibility (compact/verbose modes).
- Add visual regression snapshots for key UI states.
- Add keyboard shortcuts for toggling side panels and navigating citations.
