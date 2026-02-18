# Refactor Plan — Generation Controls + Finance Tool UI Integration (15 Feb 2026 21:12:45)

## Scope
Implement a UX/backend update to decouple generation controls and improve tools-first presentation:
- Separate `enable_refine` from generation mode and expose as an explicit toggle.
- Keep "thinking" mode as answer-style/comprehensiveness, independent of refine.
- Initialize EdgarTools user identity from `USER_EMAIL`.
- Render finance tool outputs (price chart + company/news snapshots) in a dedicated UI section separate from LLM answer markdown.
- Render `[tool=...]` markers as user-friendly chips/labels in answer text.
- Infer doc index path for ingested companies from ingest profile artifacts instead of requiring `FINRAG_DOC_INDEX_PATH`.

## Technical Approach
1. Generation controls
- Update preset semantics so `thinking` no longer implies refine by default.
- Add `enable_refine` checkbox in UI and include it in `/query_stream` payload.
- Keep draft panel visibility based on explicit refine flag and streamed events.

2. EdgarTools identity
- In finance tool adapter, before constructing `edgar.Company`, call `edgar.set_identity(USER_EMAIL)` when env var is set.
- Surface clear tool error when identity initialization fails.

3. Tool results visualization
- Add a dedicated "Tool snapshot" section in answer pane.
- Render structured cards:
  - `yfinance_get_price_history`: simple SVG line chart + latest/min/max summary.
  - `yfinance_get_ticker_info`: company + valuation/market metrics rows.
  - `yfinance_get_ticker_news`: headline list with links/timestamps.
  - generic fallback card for other tools.
- Continue passing tool context to the final LLM call; this is supplementary UI only.

4. Citation rendering for tools
- Extend citation linkifier to transform `[tool=...]` into styled non-clickable chips.
- Preserve existing doc citation click-to-source behavior.

5. Ingest profile-based doc index inference
- Add fallback resolution in ingested companies service:
  - explicit env path first (if set),
  - else resolve active ingest profile + chunk/build settings and derive `.../chunked_<max>_<overlap>/doc_index.jsonl`.
- Update status/warning text in UI and endpoint docs to match inferred behavior.

## Phases
### Phase 1: Backend runtime updates
Acceptance criteria:
- `thinking` mode no longer forces refine.
- Query settings accept explicit refine override end-to-end.
- EdgarTools calls use `USER_EMAIL` identity when present.
- Ingested companies endpoint works without `FINRAG_DOC_INDEX_PATH` when profile artifacts exist.

### Phase 2: Frontend generation controls and tool rendering
Acceptance criteria:
- Refine checkbox appears and controls draft/refine behavior independently of mode.
- Tool snapshot renders structured cards and chart in a section separate from final answer text.
- `[tool=...]` markers are visually formatted.

### Phase 3: Validation and docs
Acceptance criteria:
- TypeScript builds.
- `pre-commit run --all` passes.
- `pytest -vvv tests/` passes.
- `CHANGELOG.md` and `agent_logs/LOGBOOK.md` updated with behavior changes and validation notes.

## Files To Change
- `src/andromeda/generation_controls.py`
- `src/andromeda/finance_tools.py`
- `src/andromeda/ingested_companies.py`
- `src/andromeda/main.py`
- `src/andromeda/static/index.html`
- `src/andromeda/static/ts/index/dom.ts`
- `src/andromeda/static/ts/index/generation.ts`
- `src/andromeda/static/ts/index/main.ts`
- `src/andromeda/static/ts/index/citations.ts`
- `src/andromeda/static/ts/index/ingested.ts`
- `CHANGELOG.md`
- `agent_logs/LOGBOOK.md`

## New Files
- none

## Future Add-ons (out of current scope)
- Tool-specific expandable inspectors with pagination for long news lists.
- Candlestick chart mode with volume overlay.
- User-facing toggles per tool family (`yfinance`, `edgar`, `rag`) in the query form.
