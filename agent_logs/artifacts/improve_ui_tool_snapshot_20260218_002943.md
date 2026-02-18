# Improve Tool Snapshot UI + Interactive Price Chart (2026-02-18 00:29:43)

## Scope
Improve answer-pane "Tool snapshot" usability and visual quality by:
- fixing title overflow/cramping,
- replacing code-like EDGAR titles with professional labels,
- replacing raw EDGAR JSON rendering with structured human-readable tables,
- adding click-to-enlarge interactive price chart (candlestick-capable).

## Technical approach

### Phase 1: Layout + naming polish
- Update `src/andromeda/static/index.html` CSS for tool cards:
  - make card headers wrap safely,
  - prevent title overflow,
  - tighten spacing hierarchy for readability,
  - improve small-screen behavior.
- Update tool renderer in `src/andromeda/static/ts/index/main.ts`:
  - map internal tool IDs to user-facing names.

Acceptance criteria:
- No card title text exceeds card bounds.
- `edgar_get_financial_metrics` and `edgar_get_financial_statements` render with professional labels.

### Phase 2: EDGAR human-readable rendering
- Add EDGAR-specific renderers in `src/andromeda/static/ts/index/main.ts`:
  - financial metrics table (period + metric columns),
  - statement preview table with key line items and values.
- Keep fallback card only for unsupported payload shapes.

Acceptance criteria:
- EDGAR cards no longer show raw JSON blob by default.
- Non-technical user can read period/metric/values directly from table-style UI.

### Phase 3: Interactive enlarged price chart
- Add modal markup/CSS in `src/andromeda/static/index.html`.
- Add chart interaction logic in `src/andromeda/static/ts/index/main.ts`:
  - click mini card opens modal,
  - candlestick rendering when OHLC fields exist,
  - hover crosshair + tooltip with date/OHLC/close/volume.

Acceptance criteria:
- Clicking price-history card opens enlarged chart.
- User can inspect values interactively via hover.
- Candlestick chart is shown when OHLC data is available.

### Phase 4: Rebuild + verification + docs
- Rebuild JS from TS.
- Run required checks:
  - `source .venv/bin/activate && pre-commit run --all`
  - `source .venv/bin/activate && pytest -vvv tests/`
- Update `CHANGELOG.md` and append `agent_logs/LOGBOOK.md` with results.

Acceptance criteria:
- Required checks pass or failures are documented with concrete details.
- Changelog/logbook capture behavior changes and validation evidence.

## files_to_change
- `src/andromeda/static/index.html`
- `src/andromeda/static/ts/index/main.ts`
- `src/andromeda/static/js/index/main.js` (generated via TypeScript build)
- `CHANGELOG.md`
- `agent_logs/LOGBOOK.md`

## new_files
- `agent_logs/improve_ui_tool_snapshot_20260218_002943.md`

## Suggestions / future work (not in this scope)
- Add timeframe switchers (1M/3M/6M/1Y/YTD) in expanded chart modal.
- Add export actions (PNG/CSV) for chart and EDGAR tables.
- Add compact sparkline summaries in history thread for tool-heavy answers.
