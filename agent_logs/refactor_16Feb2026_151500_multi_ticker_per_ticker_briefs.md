# Multi-Ticker Root Fix: Per-Ticker Brief Pipeline (16Feb2026 15:15)

## Objective
Implement expert suggestion #6: for multi-ticker queries, generate per-ticker briefs first (in parallel), then synthesize a final answer from those briefs. Preserve single-ticker behavior and expose controls for brief length and overall answering effort.

## Technical Approach
- Extend generation settings and request schema with multi-ticker controls:
  - `brief_max_tokens`: per-ticker brief context/token budget
  - `answering_effort`: low/medium/high synthesis effort profile
- Add planner output flag to explicitly trigger dedicated multi-ticker brief pipeline.
- In `RAGService.execute_query_pipeline`, branch into dedicated multi-ticker flow when planner indicates multi-ticker query:
  - Retrieve/rerank per ticker (parallelized with `ThreadPoolExecutor`)
  - Generate per-ticker brief per ticker (parallelized with `asyncio.gather` + `asyncio.to_thread`)
  - Build final synthesis prompt from ticker briefs and available tool context
- Add stream events for per-ticker progress and token deltas so frontend can render each ticker panel incrementally.
- Add UI controls and answer-pane sections to show per-ticker streaming outputs and configure brief/effort controls.

## Phases

### Phase 1: Backend data model + planner + pipeline branching
- Scope:
  - Add `answering_effort` enum and `brief_max_tokens` in settings/request models.
  - Add planner field `use_multi_ticker_briefs` and resolve default behavior for multi-ticker comparison intents.
  - Extend pipeline execution object to store per-ticker retrieval/rerank/brief artifacts.
- Acceptance criteria:
  - Single-ticker requests behave unchanged.
  - Multi-ticker planned queries set dedicated branch flag and execute without regression.

### Phase 2: Parallel per-ticker retrieval/rerank + brief generation + synthesis
- Scope:
  - Implement per-ticker retrieval/rerank in parallel.
  - Implement per-ticker brief prompt + generation in parallel.
  - Implement final synthesis prompt consuming ticker briefs and tool context.
- Acceptance criteria:
  - Per-ticker briefs are generated independently and attached to pipeline output.
  - Final response synthesis references per-ticker briefs and returns answer text.

### Phase 3: Streaming and frontend ergonomics
- Scope:
  - Add NDJSON events for per-ticker stage updates and per-ticker brief deltas.
  - Render per-ticker brief cards/panels in frontend answer pane.
  - Add advanced controls for `brief_max_tokens` and `answering_effort` in query form and payload.
- Acceptance criteria:
  - During streamed run, each ticker’s brief appears incrementally in UI.
  - Final answer still streams and renders in existing final panel.

### Phase 4: Tests + docs/logging/changelog
- Scope:
  - Add/extend backend unit tests and UI streaming test coverage.
  - Update `CHANGELOG.md` and append `agent_logs/LOGBOOK.md` entry.
  - Run required lint and tests.
- Acceptance criteria:
  - `pre-commit run --all` passes.
  - `pytest -vvv tests/` passes.
  - Relevant UI tests pass or are documented if not executable in current environment.

## files_to_change
- `src/finrag/generation_controls.py`
- `src/finrag/query_runtime.py`
- `src/finrag/query_streaming.py`
- `src/finrag/main.py` (if request plumbing updates are needed)
- `src/finrag/qa.py` (new brief/synthesis prompt builders)
- `src/finrag/static/index.html`
- `src/finrag/static/ts/index/dom.ts`
- `src/finrag/static/ts/index/main.ts`
- `src/finrag/static/ts/index/generation.ts` (if needed for preset propagation)
- `tests/test_query_runtime_tools_first.py`
- `tests/ui/index.spec.ts`
- `CHANGELOG.md`
- `agent_logs/LOGBOOK.md`

## new_files
- None expected.

## Risks / Notes
- Streaming concurrent per-ticker deltas must remain cancellation-safe.
- Need to avoid large latency spikes from too many parallel ticker tasks; cap worker count by ticker count.
- Keep payload backward compatibility for clients not expecting per-ticker events.

## Suggested future add-ons (out of scope for this change)
- Adaptive per-ticker budget allocation based on retrieval confidence.
- Facet-aligned pairwise comparison stage before synthesis.
- Persist per-ticker brief artifacts for audit and answer-debugging.
