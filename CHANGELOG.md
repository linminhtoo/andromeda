# Changelog

All notable changes to this package will be documented in
this file.

This format is based on [Keep a Changelog](https://keepachangelog.com/).

---

## Template (do not modify this)

### Added

### Changed

### Fixed

### Removed

### Dev

---

## Unreleased (modify this)

### Added
- Comparison-structured synthesis controls for multi-ticker answering:
  - `comparison_required` support in `build_multi_ticker_synthesis_prompt(...)` and
    `build_multi_ticker_refine_prompt(...)` with an explicit output contract for side-by-side analysis.
- Planner fallback utility `infer_unindexed_tickers_from_question(...)` to detect ticker candidates that are referenced
  but not currently indexed.
- Eval runner retry-timeout controls:
  - `query_retry_timeout_multiplier`
  - `query_retry_timeout_cap_s`
  - CLI flags `--query-retry-timeout-multiplier` and `--query-retry-timeout-cap-s` in `scripts/run_eval.py`.
- Planner characteristics evaluation pipeline:
  - eval schema/models in `src/andromeda/eval/planner_schema.py`
  - manually curated 100-query dataset builder in `src/andromeda/eval/planner_dataset.py`
  - scoring/summary utilities in `src/andromeda/eval/planner_scoring.py`
  - CLI scripts:
    - `scripts/make_planner_eval_set.py`
    - `scripts/run_planner_eval.py`
    - `scripts/score_planner_eval.py`
    - `scripts/run_planner_eval_suite.sh`
  - generated dataset artifact:
    - `eval/eval_queries_planner_characteristics_manual100_20260219.jsonl`
  - test coverage:
    - `tests/test_planner_eval_pipeline.py`

### Changed
- `PlannedQuery` now carries planner `characteristics` through execution so downstream generation can apply
  comparison-specific synthesis constraints.
- Query planning now refuses (instead of entering clarification loops) when no indexed ticker can be resolved but
  unindexed ticker candidates are detected from the query.
- Eval generation retries now use per-attempt timeout budgets (scaled by multiplier and capped) and persist timeout
  telemetry (`query_timeout_attempt_s`, retry parameters) in generation settings for postmortems.

### Fixed

### Removed

### Dev

---


## v1.10.0 - 18 Feb 2026

### Added
- Planner fallback heuristics module at `src/andromeda/query/planner_heuristics.py` to isolate regex/keyword logic from normal runtime flow.

### Changed
- Query planning is now planner-first with explicit multi-label `characteristics` in `PlannerDecision`; routing defaults derive from planner output rather than question regex checks.
- Planner execution now attempts a structured-output repair call after both malformed planner JSON and primary planner call errors; heuristic fallback is used only if both attempts fail.
- Fallback ticker inference now uses `yfinance.Search(...)` and intersects results with indexed tickers instead of regex ticker extraction.
- Tools-first routing defaults were tightened:
  - non-narrative market/financial metric requests default to finance tools without mandatory RAG,
  - mixed narrative + market/financial requests can enable both RAG and tools.

### Removed
- Removed brittle runtime heuristic stages from active execution path:
  - narrative retrieval-query expansion
  - narrative aspect-coverage chunk post-processing
  - MMR chunk diversification
  - adaptive retrieval-budget lowering
- Removed corresponding heuristic helper implementations from `src/andromeda/query/runtime.py`; fallback heuristics now live in the dedicated planner fallback module.



## v1.9.0 - 18 Feb 2026

### Added
- Open-ended eval experiment harness scripts for 100-question faithfulness/helpfulness-focused runs (with `12` generation threads, `12` judge workers, and `350s` timeout settings) under `agent_logs/`.
- Open-ended iteration summary artifacts:
  - `agent_logs/reports/openended_iteration_metrics_20260217.csv`
  - `agent_logs/reports/openended_iteration_summary_20260217.md`
- Interactive price-chart modal in the main query UI (`src/andromeda/static/index.html`, `src/andromeda/static/ts/index/main.ts`) with hover inspection and candlestick rendering when OHLC data is available.
- Canonical eval orchestration scripts:
  - `scripts/prepare_eval_assets.sh` to rebuild chunk512 eval assets and query sets
  - `scripts/run_full_eval_suite.sh` to run single/multi/open eval tracks in one pass with a manifest output.
- `agent_logs/README.md` with non-breaking nested folder conventions for future artifacts.

### Changed
- Project/package rename from `finrag` to `andromeda` across Python module paths, imports, scripts, tests, and project metadata (including `pyproject.toml`, pre-commit path filters, and launch entrypoints).
- Strengthened narrative answer guardrails in `src/andromeda/llm/qa.py` to explicitly separate filing year vs covered fiscal period.
- Expanded narrative-intent detection and retrieval-query diversification in `src/andromeda/query/runtime.py` for open-ended prompts (growth/risk/capital-allocation/execution/demand framing).
- Added dynamic period-scope prompt notes in `src/andromeda/query/runtime.py` based on retrieved chunk metadata (`filing_date` vs `period_end_date`) to reduce unsupported year-scope claims.
- Updated benchmark-backed default generation profile to `normal` mode with high answering effort (`top_k_retrieve=40`, `top_k_rerank=25`, `draft_max_tokens=65536`, `final_max_tokens=32768`, rerank on, refine off).
- Switched narrative query expansion to default-off (`FINRAG_ENABLE_NARRATIVE_QUERY_EXPANSION=0`) while keeping narrative aspect-coverage default-on.
- Updated eval CLI/harness defaults for current local-vLLM operating point:
  - `scripts/run_eval.py`: concurrency `12`, `thread` backend, query timeout `350s`
  - `scripts/score_eval.py`: judge workers `12`, judge timeout `350s`
  - `src/andromeda/eval/runner.py` and `src/andromeda/eval/scoring.py` defaults aligned accordingly.
- Simplified frontend trade-off controls in `src/andromeda/static/index.html` and index JS/TS:
  - removed raw per-request retrieval/token numeric knobs from UI,
  - kept high-impact knobs only (`mode`, `answering_effort`, optional `enable_refine`).
- Refreshed `.env.example` to benchmark-backed defaults (`chunk 512/64`, `eval_revamp_combined_512_20260217` profile path/schema, narrative retrieval toggles).
- Refined the "Tool snapshot" cards to avoid header overflow/cramped rendering and replaced internal code-style tool names with polished user-facing titles.
- Replaced EDGAR tool raw JSON rendering in the UI with structured, human-readable metric/statement tables so financial outputs are understandable to non-technical users.
- Reorganized backend module layout for clearer grouping:
  - `query_runtime.py` -> `query/runtime.py`
  - `query_streaming.py` -> `query/streaming.py`
  - `query_conversation.py` -> `query/conversation.py`
  - `runtime_builders.py` -> `runtime/builders.py`
  - `history_store.py` -> `history/store.py`
  with import updates across app code and tests.

### Dev
- Added github `ci.yaml`


## v1.8.0 - 17 Feb 2026

### Added
- Dedicated multi-ticker map/reduce answering path in `src/andromeda/query_runtime.py`:
  - planner signal `use_multi_ticker_briefs`
  - per-ticker retrieval/rerank fan-out in parallel
  - per-ticker brief generation in parallel
  - final synthesis from per-ticker briefs.
- New generation controls for multi-ticker behavior:
  - `brief_max_tokens` (per-ticker brief budget)
  - `answering_effort` (`low`/`medium`/`high`)
  exposed in API request models, runtime settings, and frontend advanced controls.
- New QA prompt builders in `src/andromeda/llm/qa.py`:
  - `build_ticker_brief_prompt(...)`
  - `build_multi_ticker_synthesis_prompt(...)`
  - `build_multi_ticker_refine_prompt(...)`.
- Streaming events for per-ticker subagent ergonomics in `src/andromeda/query_streaming.py`:
  - `briefs_start`
  - `ticker_brief_delta`
  - `ticker_brief_done`
  - `briefs_done`.
- Frontend answer-pane support for streamed per-ticker brief cards:
  - new "Per-ticker briefs" panel in `src/andromeda/static/index.html`
  - streaming render support in `src/andromeda/static/ts/index/main.ts`.
- Test coverage updates:
  - multi-ticker brief pipeline path in `tests/test_query_runtime_tools_first.py`
  - generation control parsing for effort/brief budget in `tests/test_generation_controls.py`.
- Eval pipeline upgrades:
  - New `helpfulness_v1` judge integrated into default scoring for factual/open-ended/distractor/comparison queries.
  - Multi-judge fail-rate reporting in eval summaries (`*_judge_fail_rates`) plus explicit `*_helpfulness_fail_rate` fields.
  - Edgar-backed factual-label validation module (`src/andromeda/eval/ground_truth_validation.py`) and `make_eval_set.py` CLI switches:
    - `--validate-factual-with-edgar`
    - `--edgar-drop-mismatched`
    - `--edgar-rel-tol`
    - `--factual-candidate-multiplier`
  - Eval runner thread backend support for high-throughput environments without multiprocessing semaphores:
    - `RunConfig.parallel_backend`
    - `scripts/run_eval.py --parallel-backend {process,thread}`.
- New tests:
  - `tests/test_eval_ground_truth_validation.py`
  - extended `tests/test_eval_runner.py` for thread backend and timeout behavior
  - new year-window inference coverage in `tests/test_query_runtime_tools_first.py`.
- Eval dashboard harness:
  - `scripts/eval_dashboard.py` to aggregate run configs + generation/scoring metrics and render:
    - `metrics_runs.csv`
    - `metrics_runs.json`
    - `index.html` (trend + comparison view).

### Changed
- Planner instruction contract now explicitly asks for `use_multi_ticker_briefs=true` on comparison-style multi-entity queries.
- Streaming pipeline now executes `execute_query_pipeline(..., generate_multi_ticker_briefs=False)` and streams per-ticker brief generation live before final synthesis.
- Progress pipeline UI now includes a dedicated `briefs` step.
- Query planning now infers filing-date windows from explicit year mentions in question text when no date filters are provided (e.g., `2025` -> `2025-01-01..2025-12-31`).
- QA prompts now enforce stronger evidence discipline:
  - disallow unsupported factual inference
  - require citations for every material claim
  - explicitly call out missing-period evidence instead of guessing.
- Eval run artifact defaults now preserve full chunk payloads unless explicitly overridden:
  - `scripts/run_eval.py` defaults `--chunk-text-chars=0`, `--chunk-context-chars=0`
  - `RunConfig` defaults in `src/andromeda/eval/runner.py` aligned to full chunk persistence.
- Eval runner chunk payload truncation overrides were removed:
  - deleted `--chunk-text-chars` and `--chunk-context-chars` from `scripts/run_eval.py`
  - `RunConfig` in `src/andromeda/eval/runner.py` now always persists full `text` and `context` for retrieved chunks.
- Judge context assembly in `src/andromeda/eval/scoring.py` now prioritizes answer-cited chunk IDs before other retrieved chunks under char budget.
- `factual_correctness_v1` judge instruction in `src/andromeda/eval/judges.py` now treats evidence/context as source of truth when `Expected` conflicts with provided evidence.


## v1.7.0 - 15 Feb 2026
### Added
- Tools-first query orchestration in `src/andromeda/main.py` with explicit planner tool trace output (`tool_trace`) and query status signaling (`answered`, `clarification_required`, `refused`).
- Conversation-aware query fields and response metadata:
  - `conversation_id` on `QueryRequest` / `QueryResponse`
  - `clarifying_question` on `QueryResponse`
- Download cutoff control in `scripts/download.py`:
  - `--year-cutoff` to include only filings with year >= cutoff (for both 10-K and 10-Q pulls).
- PostgreSQL ticker-catalog retrieval primitive:
  - `PostgresDB.list_ingested_companies()`
  - `PostgresHybridRetriever.list_ingested_companies()`
- New modular query-serving support files:
  - `src/andromeda/query_streaming.py` (stream orchestration + cancellation registry)
  - `src/andromeda/history_store.py` (history persistence/query APIs)
  - `src/andromeda/review/source_access.py` (source file resolution and inline text loading)
  - `src/andromeda/ingestion/ingested_companies.py` (doc-index parsing + company-name caching)
- Runtime service builder module:
  - `src/andromeda/runtime_builders.py` for env/config parsing, LLM/retriever/reranker builders, and ingestion runtime config assembly.
- Finance tool adapter module:
  - `src/andromeda/finance_tools.py` with typed wrappers for:
    - yfinance market snapshot/news/price-history fetches
    - edgartools annual/quarterly financial metrics + statement snapshots
- Finance tool result payload surfaced in API responses:
  - `QueryResponse.tool_results`
  - normalized status enum (`ok`, `no_data`, `error`)
- New backend tests for tools-first orchestration:
  - `tests/test_finance_tools.py`
  - `tests/test_query_runtime_tools_first.py`
- Dedicated answer-pane finance snapshot section in the main UI:
  - separate tool results panel with chart/cards rendering for
    - `yfinance_get_price_history`
    - `yfinance_get_ticker_info`
    - `yfinance_get_ticker_news`
  - independent from final LLM markdown answer rendering.
- Tool citation chip rendering in answer markdown for `[tool=...]` markers.

### Changed
- Ingestion now defaults to profile-first artifact layout:
  - `download`, `process_html_to_markdown`, and `chunk` write under `data/ingest_profiles/<profile>/...` when output dirs are not explicitly provided.
  - `build_index` now defaults `--ingest-output-dir` from profile chunk settings (or profile-scoped chunk path fallback).
  - `build_index` and runtime config now default PostgreSQL schema to the active ingest profile name when schema is not explicitly set.
- Shell wrappers now default to profile-scoped paths/schema:
  - `scripts/download.sh`
  - `scripts/process_html_to_markdown.sh`
  - `scripts/chunk.sh`
  - `scripts/build_index.sh`
- `MarkdownTablePreservingChunker` now uses a Hugging Face tokenizer for token counting and overlap windows instead of whitespace heuristics, improving adherence to `max_tokens`/`overlap_tokens`.
- Reduced query-pipeline duplication in `src/andromeda/main.py` by introducing shared `RAGService` helpers for:
  - retrieval filters
  - retrieval and reranking
  - draft/final prompt construction
  - response assembly
- Refactored `/query_stream` to reuse the same `RAGService` query helpers used by `answer_question()`, and consolidated repeated draft/final token streaming loops into one local stage helper.
- `/query` and `/query_stream` now run a planner stage before retrieval and can short-circuit with clarification/refusal responses without entering retrieval/rerank generation stages.
- Multi-entity retrieval now supports per-ticker retrieval fan-out + merge with ticker-coverage-aware rerank post-processing to improve recall on comparison questions.
- Frontend query client now persists `conversation_id` across turns and handles clarification/refusal responses in-stream without breaking source/citation rendering.
- Added shared pipeline execution abstraction in `RAGService`:
  - `execute_query_pipeline(...)`
  - `response_from_pipeline(...)`
  so `/query` and `/query_stream` now consume the same tools-first plan/retrieve/rerank execution path.
- Extracted shared streamed token stage helper (`stream_text_stage(...)`) to reduce complexity inside `/query_stream` and keep stage streaming behavior reusable.
- Refactored `src/andromeda/main.py` from mixed runtime logic to API wiring:
  - `/query_stream` now delegates to `run_query_stream(...)`
  - `/history`, `/source`, and `/ingested_companies` endpoints delegate to dedicated service modules
  - file length reduced substantially while preserving endpoint behavior.
- `RAGService` planner now requests structured JSON responses via `llm.chat(..., response_model=PlannerDecision)` and falls back to robust JSON extraction/validation only when needed.
- Query orchestration status/action semantics are now represented by enums in `query_runtime`:
  - `QueryStatus` for response/planning status (`answered`, `clarification_required`, `refused`)
  - `PlannerAction` for planner decisions.
- Markdown chunk exports now include `line_start`/`line_end` metadata for `MarkdownTablePreservingChunker` chunks, and query payloads now include `source_text` (original chunk text) alongside retrieval text.
- Planner/runtime now supports tool-mix directives for each question:
  - `use_yfinance`
  - `use_edgar_financials`
  - `use_rag` (RAG treated as callable function, so retrieval can be skipped for simple tool-answerable queries)
- Query pipeline execution order is now:
  - plan
  - finance tools
  - optional RAG retrieval/rerank
  - answer synthesis over tool outputs + retrieved chunks
- Prompt builders now accept explicit tool context:
  - `build_draft_prompt(..., tool_context=...)`
  - `build_refine_prompt(..., tool_context=...)`
- Streaming API now emits finance tool stage/output events:
  - status step `tools`
  - `tool_results` event payload
  - `tools_ms` timing capture
- Main query UI stream client now renders a live `tool_results` snapshot in the answer pane while final text generation is still in progress.
- Generation control UX now decouples answer depth from two-stage refine:
  - `thinking` mode now controls comprehensive answer style only.
  - `enable_refine` is explicitly user-toggleable and independent from mode.
- EdgarTools integration now sets SEC user identity from `USER_EMAIL` via `edgar.set_identity(...)`, and emits a clear tool error when identity is missing/unset.
- `/ingested_companies` no longer depends solely on `FINRAG_DOC_INDEX_PATH`:
  - resolves from env var when explicitly set,
  - otherwise infers `doc_index.jsonl` from active ingest-profile chunk artifacts with latest-path fallback.
- Main UI now renders finance tool outputs in a dedicated panel instead of injecting snapshot markdown into final answer text.

### Fixed
- Citation source jumps now prioritize deterministic line-span highlights (when available) and otherwise match using `source_text` instead of retrieval-enriched text, improving in-file jump accuracy.


## v1.6.0 - 14 Feb 2026
### Added
- Sparse retrieval method selection across runtime and indexing:
  - `POSTGRES_SPARSE_SEARCH_METHOD` env var
  - `--sparse-search-method` in `scripts/build_index.py`
- Probabilistic chunk-level debug logging for indexing transparency in `scripts/build_index.py`:
  - `--debug-sample-rate` to randomly sample chunks for full payload logs
  - `--debug-max-samples` to cap sampled logs per run
  - `--debug-sample-seed` for deterministic sampling
  - sampled payload includes original text, retrieval fields, embedding text, embedding dimension/preview, and metadata
- Context-situating token budget controls for indexing:
  - `--context-max-tokens` in `scripts/build_index.py`
  - `CONTEXT_MAX_TOKENS` passthrough in `scripts/build_index.sh`
- Playwright UI automation harness for the main `/` app:
  - `playwright.config.ts`
  - npm scripts: `test:ui`, `test:ui:headed`, `playwright:install`
  - deterministic mocked interaction tests in `tests/ui/index.spec.ts`
- Fast frontend unit-test layer with Vitest:
  - `vitest.config.ts`
  - npm scripts: `test:unit`, `test:unit:watch`
  - focused unit suites for `markdown.ts` and `citations.ts` in `tests/ui-unit/`
- Ticker-only on-the-fly ingestion background jobs in the API:
  - `POST /ingest` now accepts JSON payload with one or more tickers (`{ticker, per_company}` or `{tickers, per_company}`)
  - `GET /ingest/{job_id}` returns lifecycle status for polling
  - new backend orchestration module `src/andromeda/ingestion/ingestion_jobs.py` runs:
    `download -> process_html_to_markdown -> chunk -> build_index`
- Durable ingest-profile storage on disk (`data/ingest_profiles/*.json`) with step-level settings capture for:
  - `scripts/download.py`
  - `scripts/process_html_to_markdown.py`
  - `scripts/chunk.py`
  - `scripts/build_index.py`
- Main UI controls for ticker ingestion:
  - ticker + files/company inputs
  - ingestion status pill/message
  - automatic status polling and ingested-company panel refresh on success

### Changed
- Default sparse ranking method is now BM25 (`pg_textsearch`) with PostgreSQL FTS as an explicit alternative.
- Retrieval/indexing now enforce sparse-method compatibility per schema and raise clear errors on mismatches.
- Context-situating LLM calls now apply an explicit generation cap (`max_tokens=256`) to keep summaries bounded.
- On-the-fly ingestion now reuses active runtime settings for schema compatibility:
  - PostgreSQL DSN/schema
  - sparse method
  - context strategy/window/metadata key
  - embedding/context LLM provider + model/base URL settings
- On-the-fly ingestion now loads settings from persisted ingest profiles first (schema/profile scoped), then falls back to env defaults.
- Ingestion now supports multiple tickers in one job request (`tickers` array), while retaining single-`ticker` compatibility.
- `scripts/build_index.sh` now sources `--context` and `--context-window` from env (`CONTEXT_STRATEGY`, `CONTEXT_WINDOW`) instead of hardcoded literals.
- `scripts/chunk.sh` now sources chunk sizing from env (`CHUNK_MAX_TOKENS`, `CHUNK_OVERLAP_TOKENS`) instead of hardcoded literals.
- Main query UI now defaults to a more compact layout:
  - progress activity feed is collapsed by default
  - draft panel is hidden by default for non-refine modes
  - layout width and answer readability spacing were tightened
- Main query UI history now groups by `conversation_id` so multi-turn exchanges appear as one conversation entry in the sidebar and render as a single scrollable thread in the answer pane.
- Main query UI desktop layout now uses a wider container and rebalanced pane constraints so the central answer area has more horizontal room on large screens.
- `/ingested_companies` now returns per-ticker document metadata (count/chunk totals/latest filing + document list), and the UI ingested panel now renders interactive expandable ticker cards with document-level details and source/chunk links.
- QA citation prompting now explicitly asks for chunk-level inline citations in the form `[doc=... chunk=...]`.

### Fixed
- Citation links in answers now honor `chunk=` hints (when present) and jump to the matching highlighted chunk in source viewer.
- Markdown thematic breaks (`---`, `***`, `___`) now render as horizontal rules in answer panes.

### Removed
- Legacy upload+OCR ingestion API contract (`file` upload + `use_mistral_ocr` flag) from `/ingest`.

### Dev
- Pre-commit now runs frontend Vitest unit tests (`frontend-unit-tests`) for static UI/TypeScript changes.
- Pre-push now runs Playwright browser-flow checks (`frontend-ui-tests`) for frontend/UI changes.


## v1.5.0 - 14 Feb 2026
### Added
- Indexing schema selector for experiment isolation on shared Postgres instances: `--postgres-schema` / `POSTGRES_SCHEMA`.
- Frontend TypeScript build tooling (`package.json`, `tsconfig.json`) plus migrated TS sources for both UIs:
  - `src/andromeda/static/ts/index/`
  - `src/andromeda/static/ts/review/`
  - shared helpers in `src/andromeda/static/ts/shared/`

### Changed
- Main/review HTML now load compiled JS module entrypoints (`/static/js/index/main.js`, `/static/js/review/main.js`) instead of inline scripts.
- Launch scripts now compile TypeScript frontend assets before starting servers.
- `launch_review.sh` now activates `.venv` before starting uvicorn, matching the main app launcher behavior.
- Added safety guard to block destructive indexing flags on default schema unless explicitly overridden (`--allow-default-schema-mutations`).
- Runtime retriever now honors `POSTGRES_SCHEMA` so app queries can target experiment schemas consistently.


## v1.4.0 - 13 Feb 2026
### Added
- PostgreSQL-native data layer (`src/andromeda/retrieval/db.py`) with minimal corpus schema (`documents`, `chunks`) and pgvector/FTS indexes.
- PostgreSQL chunk inspection script (`scripts/inspect_collection.py`) with ticker/date filters.
- PostgreSQL retriever tests (`tests/test_retriever_postgres.py`).
- Indexing CLI flags for ANN tuning and reset flows: `--ann-hnsw-m`, `--ann-hnsw-ef-construction`, `--recreate-ann-index`, and `--reset-corpus` (with legacy `--truncate` alias).
- History persistence now stores per-request step timing (`timing_ms`) for streaming runs (`retrieve_ms`, `rerank_ms`, `draft_ms`, `final_ms`, `total_ms`).
- Review UI timing panel for eval case details, sourced from `generation.timing_ms` when available.

### Changed
- Refactored retrieval/indexing to PostgreSQL-only backend (`PostgresHybridRetriever`).
- Reworked embedding text flow to use explicit `retrieval_text` + `retrieval_context` naming.
- Updated app and eval scripts for PostgreSQL runtime assumptions.
- Rewrote README to reflect PostgreSQL-first architecture and commands.
- Strengthened typing in core runtime paths by introducing typed metadata/row models and replacing ad-hoc dict metadata access in retrieval/QA/eval code.
- ANN index management now uses HNSW-only creation; ivfflat fallback creation was removed.
- Polished both web UIs (`/` and `/review`) with a cleaner visual system and improved readability.
- Replaced the old text-only progress display in `/` with a structured step pipeline + event feed, and surfaced timing summaries in history cards.

### Fixed
- Contextual embedding flow now stores `retrieval_text` separately from `retrieval_context` instead of mixing both.

### Removed
- Qdrant backend and related tests/scripts.
- Milvus backend and related scripts.
- App-level OpenTelemetry/tracing modules and related tests/scripts.
- Legacy `index_text` references in core runtime/tests.
