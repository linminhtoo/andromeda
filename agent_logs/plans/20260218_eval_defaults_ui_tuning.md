# Eval Defaults + UI Knob Simplification Plan (18 Feb 2026)

## Goal
Set production-facing "golden" defaults using evidence from `BENCHMARK.md` + `agent_logs/LOGBOOK.md`, disable narrative query expansion by default per user preference, and simplify UI trade-off controls to only high-impact knobs.

## Technical Approach

### Phase 1: Define + document golden settings
- Add a final summary section to `BENCHMARK.md` with:
  - recommended retrieval/generation/judge defaults,
  - rationale tied to measured latency/quality trade-offs,
  - explicit caveats (judge variance, outlier sensitivity).
- Keep recommendations aligned with deploy-match eval settings and latest benchmark sweep.

Acceptance criteria:
- `BENCHMARK.md` ends with a clear "golden settings" section.
- Section references concrete measured operating points from benchmark/logbook evidence.

### Phase 2: Apply backend/default CLI settings
- Set runtime defaults to match recommendation:
  - disable narrative query expansion by default (`FINRAG_ENABLE_NARRATIVE_QUERY_EXPANSION` default off),
  - keep narrative aspect coverage default on unless contradicted by benchmark data.
- Update eval CLI defaults for recommended operational settings:
  - default eval concurrency to 12,
  - default generation timeout to 350s,
  - default thread backend for local vLLM usage.
- Update `.env.example` to reflect recommended chunk/index profile defaults (`512/64`) and document key retrieval toggles.

Acceptance criteria:
- Default behavior with no flags/env overrides matches documented golden profile.
- CLI help/default values reflect recommended eval loop operating point.

### Phase 3: Simplify frontend latency/quality controls
- Keep only key user-facing trade-off knobs:
  - mode (`quick|normal|thinking`),
  - answering effort (`low|medium|high`),
  - optional refine toggle.
- Remove low-value per-request advanced knobs from UI (raw top-k/token fields).
- Keep backend compatibility: if historical settings contain removed fields, ignore safely.
- Align fallback generation presets in frontend manager with backend presets.

Acceptance criteria:
- Advanced panel no longer exposes raw retrieval/token numeric fields.
- Requests still send valid settings payload and mode presets continue to function.
- Existing history/settings replay remains stable without runtime JS errors.

### Phase 4: Changelog + logbook + validation
- Update `CHANGELOG.md` with behavior/default changes.
- Append a concise entry in `agent_logs/LOGBOOK.md` with:
  - old vs new defaults,
  - rationale,
  - any risks/follow-ups.
- Run repository-required end-of-task checks:
  - `source .venv/bin/activate && pre-commit run --all`
  - `source .venv/bin/activate && pytest -vvv tests/`

Acceptance criteria:
- Lint/format hooks pass.
- Tests pass.
- Documentation + changelog + logbook all updated.

## files_to_change
- `BENCHMARK.md`
- `src/andromeda/query/runtime.py`
- `scripts/run_eval.py`
- `src/andromeda/static/index.html`
- `src/andromeda/static/ts/index/dom.ts`
- `src/andromeda/static/ts/index/main.ts`
- `src/andromeda/static/ts/index/generation.ts`
- `src/andromeda/static/js/index/main.js`
- `src/andromeda/static/js/index/generation.js`
- `.env.example`
- `CHANGELOG.md`
- `agent_logs/LOGBOOK.md`

## new_files
- `agent_logs/eval_defaults_ui_tuning_18Feb2026.md`

## Suggestions (not in current scope)
- Add first-class backend enum for "latency/quality profile" to reduce client-side settings coupling.
- Add server-side telemetry for knob usage and p95 latency by mode/effort to auto-tune defaults over time.
