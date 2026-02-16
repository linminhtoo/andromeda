# UI Refactor Plan - Conversation Grouping, Layout Expansion, and Ingested Companies Explorer (15 Feb 2026)

## Goal
Address three UX gaps in the main app UI:
1. Multi-turn conversations are currently shown as separate history rows; they should be grouped as a single conversation entry.
2. Desktop layout underuses horizontal space; widen content and allocate more width to the middle answer pane.
3. Ingested-companies panel is plain text; replace with an interactive explorer showing per-ticker document details.

## Technical approach

### Phase 1 - Conversation-grouped history with thread view
Acceptance criteria:
- History sidebar renders one row per conversation id (fallback for legacy/no-conversation entries).
- Selecting a conversation shows the full multi-turn thread in one scrollable view.
- New turns append to the existing active conversation instead of appearing as separate top-level rows.
- Existing single-turn selection and answer/chunk behavior remain functional.

Approach:
- Add history grouping logic in frontend (`conversation_id` keying with legacy fallback).
- Update history renderer to operate on grouped conversation summaries.
- Add thread renderer in main UI to show all turns (question + answer/status) in one pane, newest first or chronological order.
- Preserve chunk/source debug behavior by anchoring detailed chunk panes to the currently selected turn (default latest turn in conversation).

### Phase 2 - Desktop layout expansion and spacing rebalance
Acceptance criteria:
- On wide screens, overall container width increases and answer pane visibly grows.
- Sidebar does not dominate space; answer pane has clearly larger readable width.
- Splitter limits still behave correctly and remain keyboard accessible.

Approach:
- Increase page max-width and tighten side panel ratio constraints.
- Increase default source pane width sensibly while increasing max page width.
- Keep responsive behavior for <=1200px unchanged except where needed.

### Phase 3 - Interactive ingested-companies explorer
Acceptance criteria:
- Ingested companies list becomes interactive (expand/collapse per ticker).
- Each ticker shows aggregate metadata (document count, chunk totals, latest filing date where derivable).
- Each ticker section lists document-level details (form type/date/doc id/chunk count/source links where available).

Approach:
- Expand backend service payload to include per-ticker documents with normalized metadata parsed from `doc_index.jsonl` entries.
- Keep existing lightweight fields for backward compatibility (`ticker`, `company`).
- Replace plain text frontend renderer with grouped cards + expandable document table/list.

## files_to_change
- `src/finrag/static/index.html`
- `src/finrag/static/ts/index/dom.ts`
- `src/finrag/static/ts/index/history.ts`
- `src/finrag/static/ts/index/main.ts`
- `src/finrag/static/ts/index/ingested.ts`
- `src/finrag/ingested_companies.py`
- `src/finrag/main.py` (only if endpoint model/shape wiring needs touchups)
- `CHANGELOG.md`
- `agent_logs/LOGBOOK.md`

## new_files
- `agent_logs/refactor_15Feb2026_191500_ui_conversation_layout_ingested_panel.md` (this plan)
- `agent_logs/20260215_191500_validate_ui_grouping_layout_ingested.sh` (validation script to be executed)

## Constraints and assumptions
- No backend schema migration required; reuse existing `doc_index.jsonl` metadata.
- Must preserve compatibility with existing history payload shape from `/history`.
- No destructive git operations; do not revert unrelated local changes.

## Suggested future work (not in current scope)
- Add explicit conversation title generation and rename support.
- Add virtualized rendering for very large history/thread datasets.
- Add server-side grouped history endpoint to reduce client processing for large logs.
