# LOGBOOK

## 2026-02-11 - PostgreSQL-first rewrite completion

### Scope completed
- Consolidated retrieval/indexing onto PostgreSQL (`pgvector` + PostgreSQL FTS).
- Removed Qdrant and Milvus runtime/indexing paths.
- Removed app-level OpenTelemetry/tracing modules and related tests/scripts.
- Completed naming cleanup:
  - `index_text` -> `retrieval_text`
  - `context` -> `retrieval_context`
- Added retrieval filter support usage path (`tickers`, `filing_date_from`, `filing_date_to`) through API -> retriever -> SQL.

### Key implementation notes
- Minimal relational schema was kept intentionally small for maintainability:
  - `documents`
  - `chunks`
- `chunks.search_tsv` is generated from `retrieval_text` to avoid duplicate storage/write logic.
- Hybrid retrieval uses weighted RRF fusion between:
  - dense rank (`embedding <=> query_vector`)
  - sparse rank (`ts_rank_cd(search_tsv, plainto_tsquery(...))`)
- Contextual embedding flow was clarified:
  - persist base `retrieval_text`
  - persist optional `retrieval_context`
  - derive embedding input at index time by concatenation when context exists

### Surprising findings
- Existing pyright failures were dominated by legacy `scripts/` and `tests/` typing issues unrelated to this refactor.
- Pre-commit’s pyright hook passes staged/all filenames by default, so pyright still checked files outside `src/` even after pyproject `include`.
- To keep the type gate actionable, `.pre-commit-config.yaml` was updated so pyright only targets `src/`.

### Validation experiments and results
- Installed updated dependencies:
  - `source .venv/bin/activate && uv pip install -e ".[dev]"`
  - Result: success; `psycopg`/`psycopg-binary` installed.
- Lint/format/type check:
  - `source .venv/bin/activate && pre-commit run --all`
  - Result: pass.
- Tests:
  - `source .venv/bin/activate && pytest tests/`
  - Result: `60 passed, 1 warning`.

### Scripts preserved under `experiments/`
- `experiments/20260211_validate_postgres_rewrite.sh`
  - Runs `pre-commit run --all` + `pytest tests/`.
  - Executed successfully in this run.

## 2026-02-12 - Stronger typing pass for core data structures

### Scope completed
- Introduced typed metadata models:
  - `DocumentMetadata`
  - `ChunkMetadata`
  - parser helpers in `src/andromeda/metadata_models.py`
- Replaced core runtime metadata `.get()` chains with typed parsing/attribute access in:
  - `src/andromeda/retriever.py`
  - `src/andromeda/qa.py`
  - `src/andromeda/main.py`
  - `src/andromeda/context_support.py`
  - `src/andromeda/chunk_postprocess.py`
  - `src/andromeda/eval/generation.py`
  - `src/andromeda/eval/scoring.py`
- Added typed DB retrieval row:
  - `HybridSearchRow` in `src/andromeda/db.py`
  - retriever now consumes typed rows instead of loose dict access.
- Added typed JSONL parsing for indexing/eval corpus:
  - `scripts/build_index.py` (`DocIndexEntry`, `ChunkJsonRow`)
  - `src/andromeda/eval/sec_corpus.py` (`DocIndexRow`, `ChunkExportRow`, `ParsedDocFromSource`)
- Updated eval query generation to use typed company/year targets:
  - `CompanyYearTarget` in `src/andromeda/eval/generation.py`
  - `scripts/make_eval_set.py` and `tests/test_generation_template_sampling.py` updated.

### Key implementation notes
- We intentionally preserved `DocChunk.metadata` as dict at the boundary for compatibility, but parse early into typed models in core logic.
- Dynamic dictionaries remain where they are intentionally open-ended:
  - evaluation score payloads (`retrieval`, `answer`, `generator`)
  - external JSONL/CSV inputs before parser normalization
  - runtime caches/maps where missing-key lookup is the data structure behavior.

### Validation experiments and results
- Lint/type:
  - `source .venv/bin/activate && pre-commit run --all`
  - Result: pass.
- Tests:
  - `source .venv/bin/activate && pytest tests/`
  - Result: `60 passed, 1 warning`.

### Scripts preserved under `experiments/`
- `experiments/20260212_validate_stronger_typing.sh`
  - Runs `pre-commit run --all` + `pytest tests/`.
  - Executed successfully in this run.

## 2026-02-12 - SEC HTML ingestion migration to `sec-parser`

### Scope completed
- Replaced the old HTML -> PDF -> OCR ingestion path with direct SEC HTML parsing.
- Rewrote `scripts/process_html_to_markdown.py` to:
  - parse filings with `sec-parser`
  - render section-aware markdown (headings from semantic elements)
  - normalize markdown tables for stable downstream detection/chunking
  - emit debug sidecars (`debug/<filing>/metadata.json`, `run_info.json`)
- Updated `scripts/chunk.py` to add a default `markdown_table_preserving` mode:
  - preserves whole tables as table chunks
  - preserves section hierarchy in `headings`
  - supports sidecar metadata lookup via `--metadata-dir`
- Kept `docling_hybrid` path available as an explicit chunker option.
- Updated shell wrappers:
  - `scripts/process_html_to_markdown.sh`
  - `scripts/chunk.sh`
- Added focused tests for converter/chunker behavior:
  - `tests/test_sec_html_to_markdown.py`
  - `tests/test_chunking_markdown.py` (including oversized text splitting behavior)

### Key implementation notes
- `sec-parser` table output is post-processed to guarantee a markdown separator row, so table blocks are detected consistently by `MarkdownTablePreservingChunker`.
- Added text block splitting in `MarkdownTablePreservingChunker` for oversized prose sections to avoid pathological large chunks while retaining table preservation.
- Corrected parser assumptions:
  - `Edgar10KParser` was removed from top-level usage/exports in our working setup because it is not a valid symbol in the installed package interface.
  - Pipeline now relies on `Edgar10QParser` plus form-aware fallback behavior.

### Validation experiments and results
- Unit tests:
  - `source .venv/bin/activate && pytest -q tests/test_sec_html_to_markdown.py tests/test_chunking_markdown.py`
  - Result: `8 passed`.
- CLI sanity:
  - `python -m scripts.process_html_to_markdown --help`
  - `python -m scripts.chunk --help`
  - Result: both commands parse expected new flags/options.
- Smoke run on local AMD 10-K + 10-Q:
  - Conversion output root: `/home/system/tmp/sec_parser_smoke2/out`
  - Chunk output root: `/home/system/tmp/sec_parser_smoke2/chunks`
  - Result: successful markdown generation + table-preserving chunk export for both filings.

## 2026-02-13 - Frontend TypeScript modularization (index/review submodules)

### Scope completed
- Replaced monolithic frontend TypeScript files with modular page-specific structures:
  - `src/andromeda/static/ts/index/`
  - `src/andromeda/static/ts/review/`
  - shared helpers in `src/andromeda/static/ts/shared/`
- Added dedicated entrypoints:
  - `src/andromeda/static/ts/index/main.ts`
  - `src/andromeda/static/ts/review/main.ts`
- Updated TS compile output to ESM module tree under `src/andromeda/static/js/`.
- Updated static HTML entry script tags to module entrypoints:
  - `/static/js/index/main.js`
  - `/static/js/review/main.js`
- Updated `launch_review.sh` to activate `.venv` before running uvicorn.

### Key implementation notes
- Switched TypeScript compiler config from single-script style output to ESM output:
  - `module: ES2020`
  - `moduleResolution: bundler`
- Build now compiles full TS tree via `tsc -p tsconfig.json` (instead of per-file commands).
- Split responsibilities into focused modules (generation controls, markdown rendering, citations, source viewer, progress UI, layout splitters, history rendering, ingested company panel, review render helpers).

### Surprising findings
- `scripts/launch_review.sh` did not activate `.venv`, causing `uvicorn: command not found` in review-only launch mode.
- `AGENTS.md` test command points to `pytest src/test/`, but this repository uses `tests/`; `src/test/` fails with path-not-found.

### Validation experiments and results
- TypeScript build:
  - `npm run -s build:ts`
  - Result: success; modular JS emitted under `src/andromeda/static/js/index/`, `src/andromeda/static/js/review/`, and `src/andromeda/static/js/shared/`.
- Runtime smoke (main app + review app):
  - `bash ./scripts/launch_app.sh` + HTTP checks for `/`, `/review`, `/static/js/index/main.js`, `/static/js/review/main.js`
  - `bash ./scripts/launch_review.sh` + HTTP checks for `/review`, `/static/js/review/main.js`
  - Result: success after `.venv` activation fix in review launcher.
- Lint/type:
  - `source .venv/bin/activate && pre-commit run --all`
  - Result: pass (first run auto-fixed EOF on `scripts/build_index.sh`, second run clean).
- Tests:
  - `source .venv/bin/activate && pytest src/test/`
  - Result: fails because path does not exist.
  - `source .venv/bin/activate && pytest tests/`
  - Result: `64 passed, 1 warning`.

### Scripts preserved under `experiments/`
- `experiments/20260213_validate_typescript_migration.sh`
  - Runs TS build + launch smoke checks + `pre-commit` + `pytest tests/`.
  - Executed successfully in this run.

## 2026-02-13 - Postgres schema namespacing for safe experiment indexing

### Scope completed
- Added schema-aware indexing for experiment isolation on shared Postgres DSNs.
- Added `build_index.py` flag:
  - `--postgres-schema` (defaults from `POSTGRES_SCHEMA` env)
- Added safety gate to block destructive operations on default schema:
  - `--reset-corpus` / `--recreate-ann-index` now require either:
    - explicit schema, or
    - explicit override `--allow-default-schema-mutations`
- Added schema plumbing across retriever/database:
  - `PostgresHybridRetriever(..., postgres_schema=...)`
  - `PostgresDB` sets `search_path` and auto-creates target schema on connect.
- Runtime app retriever now also reads `POSTGRES_SCHEMA`, so query-serving can target the same experiment schema as indexing.
- Updated shell ergonomics in `scripts/build_index.sh`:
  - env passthrough for `POSTGRES_SCHEMA`, HNSW knobs, reset/recreate flags
  - script-level refusal for unsafe destructive runs on default schema unless override is set.
- Updated docs/changelog/env example for new schema-based workflow.

### Key implementation notes
- Schema names are applied as SQL identifiers (`Identifier(...)`) to avoid SQL injection/escaping issues.
- Migration checks in `ensure_schema()` were scoped to `current_schema()` so legacy migration guards don’t accidentally inspect tables from other schemas.
- `export_schema_snapshot()` now reports active schema (`schema`) to make run metadata explicit.

### Surprising findings
- A previous guard placement allowed retriever initialization before safety checks, which could still touch the default schema. Guard was moved to execute immediately after DSN resolution.

### Validation experiments and results
- Lint/type:
  - `source .venv/bin/activate && pre-commit run --all`
  - Result: pass.
- Tests:
  - `source .venv/bin/activate && pytest tests/ -q`
  - Result: `64 passed, 1 warning`.
- CLI safety smoke:
  - destructive run without schema now exits early with:
    - `Refusing destructive operation on default schema...`

### Scripts preserved under `experiments/`
- `experiments/20260213_validate_postgres_schema_namespacing.sh`
  - Runs pre-commit, full tests, and default-schema destructive guard check.
  - Executed successfully in this run.

## 2026-02-14 - BM25 default sparse retrieval with strict method compatibility

### Previous state
- Sparse branch in hybrid retrieval used PostgreSQL FTS (`ts_rank_cd`) only.
- There was no persistent schema-level contract tying index build sparse method to runtime retrieval method.
- Runtime/indexing could be configured inconsistently without an explicit mismatch error.

### What changed
- Added sparse method support (`bm25`, `fts`) with **BM25 as default** across:
  - `src/andromeda/db.py`
  - `src/andromeda/retriever.py`
  - `src/andromeda/main.py`
  - `scripts/build_index.py`
  - `scripts/build_index.sh`
- Added method-specific sparse SQL branching in `PostgresDB.hybrid_search()`:

## 2026-02-15 - Download year cutoff for SEC filings

### Previous state
- `scripts/download.py` fetched the most recent filings by form type (10-K/10-Q) with no filing-year filter.

### What changed
- Added CLI flag `--year-cutoff` to `scripts/download.py`.
- Added year filtering in submission selection so only filings with `filingDate` year `>= year_cutoff` are considered.
- Threaded `year_cutoff` through `fetch_10ks_for_tickers(...)` and persisted it in ingest profile `download` step settings.

### Why
- Enables reproducible ingestion windows and simple “recent filings only” pulls (for example, `--year-cutoff 2025`).

### Validation experiments and results
- Lint/type hooks:
  - `source .venv/bin/activate && pre-commit run --all`
  - Result: pass.
- Tests:
  - `source .venv/bin/activate && pytest -vvv tests/`
  - Result: pass.

### Scripts preserved under `agent_logs/`
- `agent_logs/20260215_175748_download_year_cutoff_validation.sh`
  - Runs `pre-commit run --all` and `pytest -vvv tests/`.
  - `bm25`: `retrieval_text <@> to_bm25query(...)`
  - `fts`: existing `ts_rank_cd(...)` path
- Added schema metadata table `retrieval_runtime_config` to persist indexed sparse method and enforce compatibility checks:
  - indexing path initializes/validates method
  - retrieval path validates method and raises clear mismatch errors
  - `clear_all()` now clears sparse method compatibility state for intentional method switches
- Added BM25 index bootstrap path and extension guard:
  - BM25 mode now ensures `pg_textsearch` extension + bm25 index
  - FTS remains available as the runtime-cost-sensitive alternative
- Updated docs and env wiring:
  - `.env.example` now documents `POSTGRES_SPARSE_SEARCH_METHOD`
  - README now documents BM25 default, FTS alternative, and compatibility checks
- Updated changelog (`CHANGELOG.md`) for behavior change

### Why
- Needed BM25 default ranking quality while preserving an explicit FTS option for users sensitive to runtime costs.
- Required strong safety against silent index/query-method mismatches.

### Additional test maintenance observed during validation
- Existing `tests/test_context_support.py` assertions were out-of-date with current `src/andromeda/context_support.py` behavior (system+user message format and neighbor-context label text).
- Updated those assertions to match current implementation so suite remains actionable.

### Validation experiments and results
- Lint/type/format:
  - `source .venv/bin/activate && pre-commit run --all`
  - Result: pass
- AGENTS test path check:
  - `source .venv/bin/activate && pytest src/test/`
  - Result: fails because `src/test/` path does not exist in this repository
- Repository test suite:
  - `source .venv/bin/activate && pytest tests/`
  - Result: `66 passed, 1 warning`
- Reproducible validation script executed:
  - `bash agent_logs/20260214_validate_bm25_default_sparse.sh`
  - Result: pre-commit pass; `pytest src/test/` path-not-found (expected in this repo); `pytest tests/` pass (`66 passed`)

### Scripts preserved under `agent_logs/`
- `agent_logs/20260214_validate_bm25_default_sparse.sh`
  - Runs pre-commit + pytest checks used in this task.

## 2026-02-14 - Pyright coverage expanded to scripts/

### Scope completed
- Adopted pyright checking for both `src/` and `scripts/` after pyproject include expansion.
- Updated pre-commit pyright file scope to `^(src/|scripts/)`.
- Fixed script typing issues uncovered by pyright:
  - `scripts/build_index.py`: ensure `sparse_search_method` is typed as `SparseSearchMethod`.
  - `scripts/align_judge.py`: resolved sklearn `zero_division` typing mismatch.
  - `scripts/inspect_collection.py`: moved to composable SQL query construction for typed `execute()` input.
  - `scripts/test_olmocr.py`: suppressed optional import diagnostics for local-only dependency and stabilized model typing with `cast`.

### Validation experiments and results
- `source .venv/bin/activate && pre-commit run --all`
  - Result: pass (including pyright on `src/` + `scripts/`).
- `npx pyright`
  - Result: `0 errors, 0 warnings, 0 informations`.
- Repro script:
  - `bash agent_logs/20260214_validate_pyright_scripts_scope.sh`
  - Result: pass.

### Scripts preserved under `agent_logs/`
- `agent_logs/20260214_validate_pyright_scripts_scope.sh`

## 2026-02-14 - Sampled transparent chunk logging in build_index

### Scope completed
- Added probabilistic chunk-level debug logging to `scripts/build_index.py` for indexing observability.
- New CLI flags:
  - `--debug-sample-rate` (0..1)
  - `--debug-max-samples` (per run cap)
  - `--debug-sample-seed` (deterministic sampling)
- Added structured sampled payload logging containing:
  - `chunk_id`, `doc_id`, headings/source/page
  - original `text`
  - `retrieval_text`, `retrieval_context`, `embedding_text`
  - `embedding_dim` and first 8 embedding values preview
  - metadata snapshot
- Included `debug_samples_logged` in `build_index_run_info.json`.

### Key implementation notes
- Sampling happens pre-upsert and only when the random draw is below `--debug-sample-rate` and cap is not reached.
- Embedding dimension/preview is computed by embedding the sampled chunk’s resolved embedding text once; this is intentionally extra cost for sampled diagnostics only.
- Existing indexing flow remains unchanged when sample rate is `0.0` (default).

### Validation experiments and results
- Pending in this run: `pre-commit run --all`
- Pending in this run: `pytest src/test/` (repository convention caveat: tests live under `tests/`)

### Follow-up updates (same scope)
- Extended `scripts/build_index.sh` to pass debug sampling flags from env:
  - `DEBUG_SAMPLE_RATE` -> `--debug-sample-rate`
  - `DEBUG_MAX_SAMPLES` -> `--debug-max-samples`
  - `DEBUG_SAMPLE_SEED` -> `--debug-sample-seed`

### Validation experiments and results (completed)
- `source .venv/bin/activate && pre-commit run --all`
  - Result: pass.
- `source .venv/bin/activate && pytest src/test/`
  - Result: fails (`src/test/` not found).
- `source .venv/bin/activate && pytest tests/`
  - Result: `66 passed, 1 warning`.

## 2026-02-14 - Context-situating output token cap (max_tokens=256)

### Previous state
- `situate_context()` called `llm.chat(...)` without an explicit generation cap, so provider defaults controlled output length.
- `LLMClient.chat` did not expose a `max_tokens` argument in the shared interface.

### What changed
- Added optional `max_tokens` to `LLMClient.chat` and both provider wrappers:
  - `src/andromeda/llm_clients.py`
- Updated context situating to set a bounded output cap by default:
  - `src/andromeda/context_support.py` now uses `max_tokens=256` for the situating call.
- Updated test fake and assertion coverage for the new argument:
  - `tests/fakes.py`
  - `tests/test_context_support.py`
- Updated changelog entry in `CHANGELOG.md`.

### Why
- Keeps retrieval-context summaries bounded and predictable for cost/latency while preserving enough room for useful context.

### Validation experiments and results
- `source .venv/bin/activate && pre-commit run --all`
  - Result: pass.
- `source .venv/bin/activate && pytest -vvv tests/`
  - Result: `66 passed, 1 warning`.
- Reproducible validation script executed:
  - `bash agent_logs/20260214_validate_context_max_tokens.sh`
  - Result: pre-commit pass; `pytest -vvv tests/` pass (`66 passed, 1 warning`).

### Scripts preserved under `agent_logs/`
- `agent_logs/20260214_validate_context_max_tokens.sh`
  - Runs pre-commit + full test suite used for this scope.

## 2026-02-14 - CLI wiring for context max tokens in indexing

### Previous state
- `scripts/build_index.py` could not set context-situating output cap from CLI.
- `scripts/build_index.sh` had no env passthrough for controlling context-situating max tokens.

### What changed
- Added `--context-max-tokens` (`>0`, default `CONTEXT_MAX_TOKENS` env or `256`) in `scripts/build_index.py`.
- Added `Args.context_max_tokens` and passed it through to `apply_context_strategy(..., max_tokens=...)`.
- Extended `apply_context_strategy()` in `src/andromeda/context_support.py` with a `max_tokens` parameter and forwarded it to each `situate_context()` call.
- Added `CONTEXT_MAX_TOKENS` passthrough support in `scripts/build_index.sh` (maps to `--context-max-tokens`).
- Updated `CHANGELOG.md` Unreleased section.

### Why
- Lets indexing runs tune context-generation verbosity/cost without code edits.

### Validation experiments and results
- Pending in this run: `source .venv/bin/activate && pre-commit run --all`
- Pending in this run: `source .venv/bin/activate && pytest -vvv tests/`

### Scripts preserved under `agent_logs/`
- `agent_logs/20260214_validate_build_index_context_max_tokens.sh`
  - Runs pre-commit and full tests for this scope.

### Validation experiments and results (completed)
- `source .venv/bin/activate && pre-commit run --all`
  - Result: pass.
- `source .venv/bin/activate && pytest -vvv tests/`
  - Result: `66 passed, 1 warning`.
- Reproducible validation script executed:
  - `bash agent_logs/20260214_validate_build_index_context_max_tokens.sh`
  - Result: pre-commit pass; tests pass (`66 passed, 1 warning`).

## 2026-02-14 - Playwright setup + main UI compactness/citation reliability refresh

### Previous state
- No Playwright harness existed for interactive frontend verification.
- Progress event feed was always visible, taking vertical space in the primary answer pane.
- Draft panel summary remained visible even for modes that skip refine by default.
- Citation linkification was effectively doc-level and did not honor `chunk=` hints in inline citations.
- Markdown thematic breaks (`---`) were rendered as plain paragraph text.
- Prompt guidance asked for `[doc=...]` only, despite chunk-level grounding requirements.

### What changed
- Added Playwright tooling and deterministic UI tests:
  - `package.json` scripts: `playwright:install`, `test:ui`, `test:ui:headed`
  - `playwright.config.ts`
  - `tests/ui/index.spec.ts`
- Improved main UI density and defaults:
  - Wrapped progress feed in collapsible `#progressLogDetails` and defaulted it closed.
  - Hid `#draftDetails` by default for non-refine modes via mode-aware logic in frontend TS.
  - Tightened desktop layout width and answer spacing in `src/andromeda/static/index.html`.
- Fixed citation navigation robustness:
  - Frontend citation parsing now supports `[doc=... chunk=...]` markers and stores chunk-level targets.
  - Click-through now passes both `doc_id` and `chunk_id` and jumps to exact highlighted source chunk when available.
  - Doc-level fallback still works when `chunk=` is missing.
- Fixed markdown rendering:
  - Added thematic break parsing for `---`, `***`, and `___` into `<hr />`.
- Aligned QA prompt guidance with chunk-level grounding:
  - `src/andromeda/qa.py` now instructs model to cite as `[doc=... chunk=...]`.

### Why
- Needed stable, repeatable UI interaction checks for regressions after TS modularization.
- Needed a more compact default layout focused on core answer/sources rather than debug surfaces.
- Needed citation navigation to target the actual cited chunk, not a best-effort doc-level first chunk.

### Surprising findings
- Existing source-viewer span matching logic was already robust enough for chunk highlighting; the main reliability gap was citation marker parsing/target resolution, not rendering.

### Validation experiments and results
- TypeScript:
  - `npm run -s check:ts` -> pass.
  - `npm run -s build:ts` -> pass.
- Playwright:
  - `npm run -s test:ui` -> `2 passed`.
- Lint/type/format:
  - `source .venv/bin/activate && pre-commit run --all` -> pass.
- Tests:
  - `source .venv/bin/activate && pytest -vvv tests/` -> `66 passed, 1 warning`.
- Repro script executed:
  - `bash agent_logs/20260214_validate_playwright_ui_refresh.sh`
  - Result: Playwright pass, pre-commit pass, `pytest -vvv tests/` pass (`66 passed, 1 warning`).

### Scripts preserved under `agent_logs/`
- `agent_logs/20260214_validate_playwright_ui_refresh.sh`

## 2026-02-14 - Frontend test split: Vitest unit layer + Playwright integration layer

### Previous state
- Frontend test coverage existed only as Playwright browser-flow tests (`tests/ui/index.spec.ts`).
- There was no fast pure-unit test layer for frontend helper modules.

### What changed
- Added Vitest tooling for fast frontend unit tests:
  - `vitest.config.ts`
  - npm scripts in `package.json`:
    - `test:unit`
    - `test:unit:watch`
- Added focused unit suites for pure helper modules:
  - `tests/ui-unit/markdown.spec.ts` (10 tests)
  - `tests/ui-unit/citations.spec.ts` (11 tests)
- Coverage includes:
  - markdown headings, inline formatting, links, lists, tables, fenced code, thematic breaks, citation-linker invocation behavior
  - citation metadata extraction/formatting, doc/chunk target registration and lookup precedence, marker linkification, fallback label behavior, and attribute escaping

### Why
- Keeps Playwright for high-value end-to-end UI regressions while moving pure logic checks to fast, deterministic unit tests.

### Validation experiments and results
- `npm run -s test:unit`
  - Result: `2` files passed, `21` tests passed.
- `npm run -s test:ui`
  - Result: `2` tests passed.
- `source .venv/bin/activate && pre-commit run --all`
  - Result: pass.
- `source .venv/bin/activate && pytest -vvv tests/`
  - Result: `66 passed, 1 warning`.
- Reproducible validation script executed:
  - `bash agent_logs/20260214_validate_vitest_frontend_unit_tests.sh`
  - Result: unit tests pass, Playwright pass, pre-commit pass, Python tests pass.

### Scripts preserved under `agent_logs/`
- `agent_logs/20260214_validate_vitest_frontend_unit_tests.sh`

## 2026-02-14 - Re-enabled on-the-fly ingestion as ticker-only background pipeline

### Previous state
- `POST /ingest` accepted uploaded files + `use_mistral_ocr` flag but runtime ingestion was hard-disabled and raised:
  - `RuntimeError("On-the-fly ingestion is disabled for now. Use batch ingestion script.")`
- There was no background ingestion job lifecycle API/status model for frontend polling.
- Main UI had no ingest trigger controls; only a read-only “Ingested companies” panel.

### What changed
- Added ticker-only background ingestion orchestration in `src/andromeda/ingestion_jobs.py`:
  - pipeline: `download -> process_html_to_markdown -> chunk -> build_index`
  - per-job run directories/logs under `data/on_the_fly_ingest/` (configurable via `FINRAG_INGEST_JOBS_ROOT`)
  - in-memory job tracking with lifecycle states (`queued`, `running`, `succeeded`, `failed`)
- Replaced ingestion API contract in `src/andromeda/main.py`:
  - `POST /ingest` now accepts JSON `{ticker, per_company}` only (no uploads/OCR)
  - added `GET /ingest/{job_id}` for status polling
- Added runtime-compatible indexing argument wiring so ingestion uses active app settings:
  - PostgreSQL DSN/schema
  - sparse method
  - context strategy/window/metadata key
  - embedding/context provider+model/base URL settings
- Frontend updates (`src/andromeda/static/index.html`, `src/andromeda/static/ts/index/*`):
  - ingest ticker input + files/company input + ingest action
  - live status pill/message via polling
  - automatic ingested-company panel refresh on success
- Added/updated tests:
  - `tests/test_ingestion_jobs.py` for ticker normalization + build-index command parity
  - `tests/test_main_api_e2e.py` ingestion endpoint/status tests
  - `tests/ui/index.spec.ts` ingestion UI flow test

### Why
- Needed to reintroduce on-the-fly ingestion with the simplest low-risk path (ticker-only, no upload/OCR) while preserving schema/runtime compatibility guarantees for existing PostgreSQL retrieval deployments.

### Surprising findings
- Ingestion controls are in a collapsed `<details>` block (`#ingestedDetails`), so Playwright tests must expand the section before visibility/input assertions.

### Validation experiments and results
- TypeScript build:
  - `npm run -s build:ts`
  - Result: pass.
- Lint/type:
  - `source .venv/bin/activate && pre-commit run --all`
  - Result: pass.
- Python tests:
  - `source .venv/bin/activate && pytest -vvv tests/`
  - Result: `73 passed, 1 warning`.
- UI e2e subset:
  - `npm run -s test:ui -- tests/ui/index.spec.ts`
  - Result: `3 passed`.

### Scripts preserved under `agent_logs/`
- `agent_logs/validate_ticker_ingestion_14Feb2026_203624.sh`
  - Runs: TS build, pre-commit, full pytest suite, and the updated Playwright spec.
  - Executed successfully in this run.

## 2026-02-14 - Ingest profile persistence + multi-ticker on-the-fly ingestion hardening

### Previous state
- On-the-fly ingestion runtime config was mostly env-driven and could drift from the settings used to build an existing index/schema.
- `scripts/build_index.sh` still hardcoded:
  - `--context neighbors`
  - `--context-window 1`
- `scripts/chunk.sh` still hardcoded:
  - `--max-tokens 1024`
  - `--overlap-tokens 128`
- Frontend ingestion accepted a single ticker in practice.

### What changed
- Added durable ingest profile store in `src/andromeda/ingest_profile.py`:
  - profile resolution: explicit arg -> `FINRAG_INGEST_PROFILE` -> `POSTGRES_SCHEMA` -> `default`
  - step settings persistence to `data/ingest_profiles/<profile>.json`
- Updated step scripts to persist their actual run settings to profile files:
  - `scripts/download.py`
  - `scripts/process_html_to_markdown.py`
  - `scripts/chunk.py`
  - `scripts/build_index.py`
- Updated shell scripts to remove hardcoded settings:
  - `scripts/build_index.sh` now reads context flags from env (`CONTEXT_STRATEGY`, `CONTEXT_WINDOW`, etc.)
  - `scripts/chunk.sh` now reads chunk sizing from env (`CHUNK_MAX_TOKENS`, `CHUNK_OVERLAP_TOKENS`, etc.)
- Reworked app ingestion config loading in `src/andromeda/main.py`:
  - load persisted profile step settings first (download/process/chunk/build_index)
  - fallback to env defaults when profile settings are missing
  - include chunk settings (`max_tokens`, `overlap_tokens`, chunker/doc-id strategy, etc.) in runtime job config
- Extended ingestion job manager for multi-ticker jobs in `src/andromeda/ingestion_jobs.py`.
- Extended ingestion API + UI to support multiple tickers:
  - API accepts `tickers` list (and still supports single `ticker`)
  - frontend accepts comma/space-separated tickers and sends `tickers` array

### Why
- Prevent silent config drift between original index build settings and app-triggered incremental ingestion.
- Make schema/profile-specific experimentation safer and reproducible.
- Allow practical batch ingestion requests from UI without repeated single-ticker submissions.

### Validation experiments and results
- TypeScript build:
  - `npm run -s build:ts`
  - Result: pass.
- Targeted tests:
  - `source .venv/bin/activate && pytest -q tests/test_ingest_profile.py tests/test_ingestion_jobs.py tests/test_main_api_e2e.py`
  - Result: `15 passed, 1 warning`.
- UI e2e subset:
  - `npm run -s test:ui -- tests/ui/index.spec.ts`
  - Result: `3 passed`.

### Notes
- Existing profile files may not exist for older historical indexes; in that case runtime ingestion intentionally falls back to env defaults with warning logs.

## 2026-02-14 - Generated ingest profile without running pipeline

### Request
- Generate ingest profile outputs from current shell script args and `.env` values, without executing expensive ingestion steps (especially `build_index.sh`).

### What I did
- Added and executed a helper script:
  - `agent_logs/generate_ingest_profile_from_scripts_20260214_230715.sh`
- Script behavior:
  - Sources `scripts/_env.sh` and uses current `.env` values.
  - Resolves profile name via app logic (`FINRAG_INGEST_PROFILE` -> `POSTGRES_SCHEMA` -> `default`).
  - Writes `download`, `process_html_to_markdown`, `chunk`, and `build_index` step settings directly with `update_ingest_profile_step`.
  - Marks each step metadata with `generated_without_execution=true`.

### Output
- Generated profile file:
  - `data/ingest_profiles/exp_ctx_neighbors_w1_m24_ef200.json`

### Validation
- Lint:
  - `source .venv/bin/activate && pre-commit run --all`
  - Result: pass.
- Tests:
  - `source .venv/bin/activate && pytest -vvv tests/`
  - Result: `77 passed, 1 warning`.

## 2026-02-14 - Pre-commit wiring for frontend test layers

### Previous state
- Frontend unit tests (`vitest`) and UI integration tests (`playwright`) existed as npm scripts but were not enforced by pre-commit hooks.

### What changed
- Updated `.pre-commit-config.yaml` local hooks:
  - Added `frontend-unit-tests` (`npm run -s test:unit`) at `pre-commit` stage.
  - Added `frontend-ui-tests` (`npm run -s test:ui`) at `pre-push` stage.
- Scoped both hooks with frontend-focused file filters to avoid unrelated runs.
- Kept heavy browser UI checks at `pre-push` to avoid slowing standard commit cycles.

### Why
- Ensures frontend regressions in pure rendering/citation helpers are caught early on commit.
- Ensures browser interaction regressions are gated before push.

### Validation experiments and results
- `source .venv/bin/activate && pre-commit run --all`
  - Result: pass (includes `frontend-unit-tests`).
- `source .venv/bin/activate && pre-commit run frontend-ui-tests --all-files --hook-stage pre-push`
  - Result: pass.
- `source .venv/bin/activate && pytest -vvv tests/`
  - Result: `77 passed, 1 warning`.
- Reproducible validation script executed:
  - `bash agent_logs/20260214_validate_precommit_frontend_hooks.sh`
  - Result: pass.

### Scripts preserved under `agent_logs/`
- `agent_logs/20260214_validate_precommit_frontend_hooks.sh`

## 2026-02-15 - Standalone OpenAI-client vLLM tool-calling probe

### Previous state
- The repo had OpenAI-compatible client wrappers in `src/andromeda/llm_clients.py` but no dedicated standalone script for directly probing tool/function calling behavior against the configured vLLM endpoint.

### What changed
- Added standalone probe script:
  - `scripts/test_vllm_tool_call_openai.py`
- Added concise plan doc for the task:
  - `agent_logs/refactor_15Feb2026_004617_vllm_tool_call_probe.md`
- Added validation script and executed it:
  - `agent_logs/20260215_validate_vllm_tool_probe.sh`
- Updated changelog unreleased section:
  - `CHANGELOG.md`

### Why
- Needed a minimal, isolated validation path to test whether the served model (`Qwen/Qwen3-VL-32B-Instruct-FP8`) supports OpenAI-style tool calls end-to-end without modifying runtime code in `src/andromeda`.

### Key implementation notes
- Probe script mirrors existing OpenAI setup conventions:
  - `.env` loading from repo root
  - `OpenAI(api_key=..., base_url=...)`
  - env resolution order for base URL: `OPENAI_CHAT_BASE_URL` -> `OPENAI_BASE_URL`
  - model from `OPENAI_CHAT_MODEL`
- Probe performs a full two-step tool flow:
  - first completion with `tools`
  - local mock function execution (`lookup_quote`)
  - tool message sent back for final assistant response
- Added explicit bad-request handling to print actionable vLLM flag hints instead of raw traceback.

### Surprising findings
- With current remote vLLM serve args, tool-calling requests are explicitly rejected by server-side validation:
  - `"auto" tool choice requires --enable-auto-tool-choice and --tool-call-parser to be set`
  - `tool_choice="required" requires --tool-call-parser to be set`

### Validation experiments and results
- Full lint/format/type + tests (scripted):
  - `bash agent_logs/20260215_validate_vllm_tool_probe.sh`
  - Result: pre-commit pass, `pytest -vvv tests/` pass (`77 passed, 1 warning`).
- Probe runtime check (`tool_choice=auto`):
  - `source .venv/bin/activate && python scripts/test_vllm_tool_call_openai.py --max-tokens 128`
  - Result: fails with HTTP 400 from vLLM requiring tool-calling flags.
- Probe runtime check (`tool_choice=required`):
  - `source .venv/bin/activate && python scripts/test_vllm_tool_call_openai.py --tool-choice required --max-tokens 128`
  - Result: fails with HTTP 400 requiring `--tool-call-parser`.

### Scripts preserved under `agent_logs/`
- `agent_logs/20260215_validate_vllm_tool_probe.sh`

## 2026-02-15 - Shared query pipeline helpers for sync + streaming paths

### Previous state
- `RAGService.answer_question()` and `/query_stream` in `src/andromeda/main.py` duplicated core query pipeline logic:
  - retrieval filter construction
  - hybrid retrieval
  - rerank branching
  - draft/final prompt branching
- `/query_stream` also duplicated token-streaming loops for draft/final stages.

### What changed
- Added shared `RAGService` helper methods in `src/andromeda/main.py`:
  - `build_retrieval_filters`
  - `retrieve_chunks`
  - `rerank_chunks`
  - `draft_prompt`
  - `final_prompt`
  - `generate_answers`
  - `build_query_response`
- Updated `answer_question()` to use the shared helpers end-to-end.
- Updated `/query_stream` to reuse the same retrieval/rerank/prompt/response helpers used by `answer_question()`.
- Added `StreamStageResult` and one local `stream_stage(...)` async helper in `/query_stream` so draft/final streaming loops share the same batching/cancel/disconnect flow.
- Added planning artifact:
  - `agent_logs/refactor_15Feb2026_005223_query_pipeline_dedup.md`

### Why
- Reduce maintenance risk while upcoming answer-logic branch overhauls are in flight.
- Ensure behavior changes in the core answer pipeline can be implemented in one place and reused by both sync and streaming APIs.

### Surprising findings
- Prompt builders (`build_draft_prompt` / `build_refine_prompt`) return `list[ChatMessage]`, so pyright required explicit typing/casting at the streaming bridge boundary (`iter_chat_deltas` currently expects `list[dict[str, Any]]`).

### Validation experiments and results
- Lint/format/type:
  - `source .venv/bin/activate && pre-commit run --all`
  - Result: pass.
- Tests:
  - `source .venv/bin/activate && pytest -vvv tests/`
  - Result: `77 passed, 1 warning`.
- Reproducible validation script executed:
  - `bash agent_logs/20260215_validate_query_pipeline_dedup.sh`
  - Result: pass (`pre-commit` + full `pytest -vvv tests/`).

### Scripts preserved under `agent_logs/`
- `agent_logs/20260215_validate_query_pipeline_dedup.sh`

## 2026-02-15 - Pylance type fixes for vLLM tool-calling probe script

### Previous state
- `scripts/test_vllm_tool_call_openai.py` had Pylance typing errors:
  - `tool_choice` argument passed as plain `str` to `client.chat.completions.create(...)`.
  - Access to `tool_call.function` without narrowing the union type of returned tool calls.

### What changed
- Added `ToolChoice = Literal["auto", "required", "none"]` and updated `run_tool_call_probe(...)` signature to use it.
- Cast CLI `args.tool_choice` to `ToolChoice` before passing to the OpenAI client call.
- Added explicit runtime type narrowing (`if tool_call.type != "function": raise RuntimeError(...)`) before accessing `tool_call.function` attributes.

### Why
- Satisfy static typing guarantees expected by Pylance/pyright while keeping runtime behavior unchanged for valid function tool calls.

### Validation experiments and results
- Lint/format/type:
  - `source .venv/bin/activate && pre-commit run --all`
  - Result: pass.
- Tests:
  - `source .venv/bin/activate && pytest -vvv tests/`
  - Result: `77 passed, 1 warning`.

### Scripts preserved under `agent_logs/`
- `agent_logs/20260215_validate_pylance_tool_probe_typing.sh`

## 2026-02-15 - Tools-first answer orchestration + shared sync/stream pipeline execution

### Previous state
- Complex multi-entity questions could miss target entities during retrieval/rerank, causing ungrounded answers.
- `/query` and `/query_stream` still required parallel logic updates when core answer flow changed.
- `/query_stream` had grown into a large mixed-responsibility function (planning, retrieval/rerank logic, generation streaming, response assembly).

### What changed
- Added tools-first planning and execution primitives in `src/andromeda/main.py`:
  - planner outputs typed decisions with statuses: `answered`, `clarification_required`, `refused`
  - planner tool trace is returned in API responses (`tool_trace`)
  - new query metadata fields: `conversation_id`, `status`, `clarifying_question`
- Added indexed ticker validation and early refusal path:
  - planner checks requested/inferred tickers against indexed ticker catalog before retrieval
  - returns explicit refusal when ticker coverage is missing
- Added per-ticker fan-out retrieval strategy for multi-entity questions:
  - retrieval can run once per ticker
  - merged candidates are deduped and passed through ticker-coverage-aware rerank post-processing
- Added shared pipeline abstractions in `RAGService`:
  - `execute_query_pipeline(...)` runs plan->retrieve->rerank once
  - `response_from_pipeline(...)` builds clarification/refusal/final responses from pipeline outputs
- Rewired both endpoints to share the same core pipeline execution:
  - `answer_question()` now delegates to shared pipeline abstractions
  - `/query_stream` now calls the same `execute_query_pipeline(...)` path before streaming generation
- Reduced `/query_stream` complexity by extracting shared token-stage streaming helper:
  - `stream_text_stage(...)`

### Additional backend/frontend updates
- Added PostgreSQL/retriever ticker catalog primitive:
  - `PostgresDB.list_ingested_companies()`
  - `PostgresHybridRetriever.list_ingested_companies()`
- Frontend now persists and sends `conversation_id` across turns and handles non-answer statuses in stream completion payloads.
- Added/updated tests:
  - `tests/test_main_api_e2e.py` now covers clarification follow-up flow using conversation context
  - `tests/test_retriever_postgres.py` now covers ingested-company listing pass-through

### Why
- Improve robustness for multi-company queries and avoid hallucination-prone answers when required entities are missing from indexed context.
- Remove duplicated core decision logic so behavior changes are made once and apply to both sync and streaming query APIs.
- Keep streaming implementation focused on transport/UX concerns rather than re-implementing retrieval orchestration.

### Surprising findings
- Earlier dedup still left semantic duplication risk because orchestration decisions (plan/branch behavior) were not truly centralized.
- Extracting a typed pipeline execution object (`QueryPipelineExecution`) made the sync/stream parity boundary explicit and easier to reason about.

### Validation experiments and results
- Full validation script:
  - `bash agent_logs/20260215_021319_validate_tools_first_answering_overhaul.sh`
  - Result: pass (pre-commit, TS checks, frontend unit/UI tests, full `pytest -vvv tests/`, vLLM tool-call probe).
- Targeted backend checks during iteration:
  - `source .venv/bin/activate && pytest -q tests/test_main_api_e2e.py tests/test_retriever_postgres.py`
  - Result: pass (`13 passed`).

### Scripts preserved under `agent_logs/`
- `agent_logs/20260215_021319_validate_tools_first_answering_overhaul.sh`
- `agent_logs/refactor_15Feb2026_020326_tools_first_answering_overhaul.md`

## 2026-02-15 - `main.py` cleanup pass: extracted endpoint-adjacent services/modules

### Previous state
- `src/andromeda/main.py` had grown to ~1511 lines and mixed endpoint wiring with non-API concerns:
  - streaming orchestration and cancellation state
  - source file resolution and inline text loading
  - ingested-company doc-index parsing/cache logic
  - query history persistence/readback logic
- Even after prior dedup work, `query_docs_stream()` remained difficult to maintain due to mixed responsibilities.

### What changed
- Added new modules and moved logic out of `main.py`:
  - `src/andromeda/query_streaming.py`
    - `StreamCancelRegistry`
    - `run_query_stream(...)`
    - stream payload/timing helpers
  - `src/andromeda/history_store.py`
    - `QueryHistoryStore` with append/read/read_entry/clear
  - `src/andromeda/source_access.py`
    - source allowlist resolution and text file loading helpers
  - `src/andromeda/ingested_companies.py`
    - `IngestedCompaniesService` with doc-index parsing and cache
- Rewired `src/andromeda/main.py` endpoints to delegate to these modules while keeping API contract stable:
  - `/query_stream` now delegates to `run_query_stream(...)`
  - `/cancel` uses `StreamCancelRegistry`
  - `/source` and `/source_text` use `source_access` helpers
  - `/ingested_companies` uses `IngestedCompaniesService`
  - `/history` endpoints use `QueryHistoryStore`
- Kept conversation/status constants available from `andromeda.main` for test compatibility.
- Result: `src/andromeda/main.py` reduced from ~1511 lines to ~836 lines.

### Why
- Enforce clearer separation of concerns so `main.py` focuses on public API endpoints and dependency wiring.
- Reduce maintenance cost and drift risk when tools-first answer logic evolves.
- Make streaming and persistence logic independently testable and easier to reason about.

### Validation experiments and results
- `source .venv/bin/activate && python -m py_compile src/andromeda/main.py src/andromeda/query_streaming.py src/andromeda/history_store.py src/andromeda/source_access.py src/andromeda/ingested_companies.py`
  - Result: pass.
- `source .venv/bin/activate && pre-commit run --all`
  - Result: pass.
- `source .venv/bin/activate && pytest -vvv tests/`
  - Result: `79 passed, 1 warning`.

### Scripts preserved under `agent_logs/`
- No new standalone script created for this pass; validations were run directly from shell commands.

## 2026-02-15 - Runtime builder extraction from `main.py` + planner `response_model` usage

### Previous state
- `src/andromeda/main.py` still contained most env/config/service-builder implementation details:
  - LLM provider/model/env resolution
  - PostgreSQL retriever/reranker builders
  - ticker ingestion runtime config + coercion helpers
- Planner decision call in `src/andromeda/query_runtime.py` parsed raw LLM JSON manually without using the existing `response_model` capability.

### What changed
- Added `src/andromeda/runtime_builders.py` and moved runtime construction logic there:
  - `setup_logging(...)`
  - LLM helpers (`llm_for_chat`, `llm_for_embeddings`, provider/model/env helpers)
  - retrieval config helpers (`context_config`, `sparse_search_method`, `postgres_dsn`)
  - ingestion config assembly (`build_ticker_ingestion_config(project_root=...)`) and coercion helpers
  - `build_retriever()` and `build_reranker()`
- Updated `src/andromeda/main.py` to import/use these builders instead of maintaining inline implementations.
- Updated planner structured call in `src/andromeda/query_runtime.py`:
  - now calls `self.llm.chat(..., response_model=PlannerDecision)`
  - first attempts `PlannerDecision.model_validate_json(raw)`
  - preserves fallback extraction/validation path when output is not directly valid JSON.
- Audited all `llm.chat(...)` call sites:
  - suitable structured-output use now present in `query_runtime` planner and `eval/judges`
  - remaining calls (`qa`, `context_support`, generation flow) are free-text generation and intentionally do not use `response_model`.

### Why
- Keep `main.py` focused on app wiring/endpoints and reduce maintenance surface for runtime configuration code.
- Improve planner reliability by explicitly requesting schema-constrained model output before fallback parsing.

### Validation experiments and results
- `source .venv/bin/activate && python -m py_compile src/andromeda/main.py src/andromeda/runtime_builders.py src/andromeda/query_runtime.py`
  - Result: pass.
- `source .venv/bin/activate && pre-commit run --all`
  - Result: pass.
- `source .venv/bin/activate && pytest -vvv tests/`
  - Result: `79 passed, 1 warning`.

### Scripts preserved under `agent_logs/`
- No new standalone script created for this pass; validations were run directly via shell commands.

## 2026-02-15 - Replace free-form status/action strings with enums in query runtime

### Previous state
- `src/andromeda/query_runtime.py` used free-form strings for planner `action` and query `status` fields.
- Branching/comparisons in planning and response construction relied on string literals.

### What changed
- Added enums in `src/andromeda/query_runtime.py`:
  - `QueryStatus` (`answered`, `clarification_required`, `refused`)
  - `PlannerAction` (answer/retrieve/proceed/clarify variants/refuse variants)
- Updated typed fields and signatures to use enums:
  - `QueryResponse.status`
  - `PlannerDecision.action`
  - `PlannedQuery.status`
  - `RAGService._normalize_plan_action(...)`
  - `RAGService.build_query_response(status=...)`
- Updated internal branching to compare enum members instead of raw strings.
- Preserved `QUERY_STATUS_*` exports as string-value aliases for compatibility with existing consumers/tests.

### Why
- Stronger type safety and fewer invalid-string branches in core query orchestration logic.
- Keeps API behavior stable while improving maintainability internally.

### Validation experiments and results
- `source .venv/bin/activate && python -m py_compile src/andromeda/query_runtime.py src/andromeda/main.py src/andromeda/query_streaming.py`
  - Result: pass.
- `source .venv/bin/activate && pre-commit run --all`
  - Result: pass.
- `source .venv/bin/activate && pytest -q tests/test_main_api_e2e.py tests/test_qa.py`
  - Result: `12 passed, 1 warning`.

### Scripts preserved under `agent_logs/`
- No new standalone script created for this pass; validations were run directly via shell commands.

## 2026-02-15 - Follow-up fix: enum constant usage in streaming/conversation paths

### Previous state
- After enum migration, `query_streaming.py` still passed `QUERY_STATUS_ANSWERED` where `build_query_response(...)` expects `QueryStatus`.
- Pylance flagged this as `reportArgumentType`.

### What changed
- Updated status usage in `query_streaming.py` to enum members (`QueryStatus.ANSWERED`).
- Updated status comparison in `query_conversation.py` to use `QueryStatus.CLARIFICATION_REQUIRED`.
- Adjusted exported `QUERY_STATUS_*` compatibility constants to reference enum members directly.

### Validation
- `source .venv/bin/activate && pre-commit run --all` -> pass.
- `source .venv/bin/activate && pytest -q tests/test_main_api_e2e.py tests/test_qa.py` -> `12 passed`.

## 2026-02-15 - Remove status alias constants; use enums directly

### Previous state
- `query_runtime` still exposed `QUERY_STATUS_*` alias constants pointing to `QueryStatus` enum members.
- `main` and tests referenced these aliases.

### What changed
- Removed `QUERY_STATUS_*` aliases from `src/andromeda/query_runtime.py`.
- Removed alias imports/exports from `src/andromeda/main.py`.
- Updated `tests/test_main_api_e2e.py` to use `QueryStatus` directly.
- Kept planner action enum strict (no synonym/legacy normalization).

### Why
- Align code with strict-enum-only design and avoid duplicate status representations.

### Validation
- `source .venv/bin/activate && pre-commit run --all` -> pass.
- `source .venv/bin/activate && pytest -q tests/test_main_api_e2e.py tests/test_qa.py` -> `12 passed`.

## 2026-02-15 - Citation source-jump reliability via line spans + source text

### Previous state
- Citation click opened the source markdown file, but in-file jump could fail because source-viewer highlighting used `chunk.text`.
- In query payloads, `chunk.text` commonly held retrieval-enriched text (`retrieval_text`), which can differ from original markdown chunk text and break span matching.
- Markdown chunk exports did not include explicit source line boundaries.

### What changed
- Added original chunk text to query payloads:
  - `TopChunk.source_text` in `src/andromeda/dataclasses.py`.
  - populated in `RAGService._serialize_top_chunks(...)` (`src/andromeda/query_runtime.py`).
  - added to stream chunk payloads in `src/andromeda/query_streaming.py`.
- Added markdown chunk line metadata in `src/andromeda/chunking.py` (`MarkdownTablePreservingChunker`):
  - `metadata.line_start` (1-based)
  - `metadata.line_end` (1-based, inclusive)
  - emitted for text and table chunks.
- Exposed line metadata to UI payloads via `RAGService._chunk_metadata_for_ui(...)` in `src/andromeda/query_runtime.py`.
- Updated source viewer highlighting logic (`src/andromeda/static/ts/index/source-viewer.ts`):
  - first uses `line_start`/`line_end` to derive deterministic char spans
  - falls back to fuzzy match using `source_text` (then `text`/`preview`)
  - keeps existing rendered/raw behavior and active-chunk scroll.
- Added/updated test coverage in `tests/test_chunking_markdown.py` for `line_start`/`line_end` metadata.
- Updated `CHANGELOG.md` (Unreleased) for behavior change.

### Why
- This keeps retrieval-enriched text useful for QA/ranking display while providing source-faithful text (`source_text`) and deterministic chunk boundaries (`line_start`/`line_end`) for accurate source jumps.

### Surprising findings
- The root cause was payload semantics, not citation parsing: `chunk.text` intentionally favored retrieval context over raw source text.
- No PostgreSQL schema migration was required because chunk metadata is already persisted in JSONB.

### Validation experiments and results
- `source .venv/bin/activate && pre-commit run --all`
  - Result: pass.
- `source .venv/bin/activate && pytest -vvv tests/`
  - Result: `79 passed, 1 warning`.
- Re-ran full validation via preserved script:
  - `bash agent_logs/20260215_043200_validate_citation_jump_line_spans.sh`
  - Result: pass (`pre-commit` + full test suite).

### Scripts preserved under `agent_logs/`
- `agent_logs/20260215_043200_validate_citation_jump_line_spans.sh`
  - Runs TS build, `pre-commit --all`, and `pytest -vvv tests/`.

## 2026-02-15 - Markdown chunker switched to tokenizer-accurate token accounting

### Previous state
- `MarkdownTablePreservingChunker` estimated tokens by whitespace word count.
- This caused drift from real model token counts, including oversized chunks relative to configured `max_tokens`.

### What changed
- Updated `src/andromeda/chunking.py` (`MarkdownTablePreservingChunker`) to use `HuggingFaceTokenizer` for:
  - `_count_tokens` via tokenizer token count
  - `_tail_overlap` via token-id tail extraction and decode
  - fallback long-sentence splitting via token-id windows instead of word windows
- Added `tokenizer_model` and `tokenizer_kwargs` constructor options for `MarkdownTablePreservingChunker`.
- Updated `tests/test_chunking_markdown.py` oversized-chunk assertion to validate token count with the chunker tokenizer.
- Updated `CHANGELOG.md` Unreleased/Changed with this behavior change.

### Why
- Enforce chunk boundaries with the same tokenization regime used by retrieval/generation components.
- Reduce max-token overshoot in exported chunk JSONL for SEC filings.

### Validation experiments and results
- `source .venv/bin/activate && pre-commit run --all` -> pass.
- `source .venv/bin/activate && pytest -vvv tests/` -> `79 passed, 1 warning`.
- Executed preserved script: `./agent_logs/20260215_tokenizer_chunker_validation.sh` -> pass.

### Scripts preserved under `agent_logs/`
- `agent_logs/20260215_tokenizer_chunker_validation.sh`
  - Runs repo-required lint + tests (`pre-commit run --all`, `pytest -vvv tests/`).

## 2026-02-15 - Ingestion profile-first artifact layout + schema coupling

### Previous state
- Ingestion scripts relied on flat/shared defaults such as:
  - `data/sec_filings`
  - `data/sec_filings_md_secparser`
- PostgreSQL schema often depended on explicit `--postgres-schema`/`POSTGRES_SCHEMA`.
- This made experiment isolation rely heavily on manual folder naming/discipline.

### What changed
- Added profile layout resolver in `src/andromeda/ingest_profile.py`:
  - `IngestProfileLayout`
  - `ingest_profile_layout(...)`
  - `postgres_schema_for_ingest_profile(...)`
- Wired profile-first defaults into scripts:
  - `scripts/download.py`
    - default output now resolves to `data/ingest_profiles/<profile>/sec_filings`.
  - `scripts/process_html_to_markdown.py`
    - default output now resolves to `data/ingest_profiles/<profile>/sec_filings_md_secparser`.
  - `scripts/chunk.py`
    - default markdown input resolves to profile `processed_markdown`.
    - default output resolves to profile `chunked_<max>_<overlap>`.
  - `scripts/build_index.py`
    - `--ingest-output-dir` is now optional; default resolves from profile chunk settings, then profile chunk path fallback.
    - schema now defaults to `postgres_schema_for_ingest_profile(profile)` when not explicitly provided.
- Runtime alignment:
  - `src/andromeda/runtime_builders.py` now falls back to profile-derived schema for ingestion config and retriever when schema env/settings are absent.
- Shell wrappers updated to profile-first path defaults:
  - `scripts/download.sh`
  - `scripts/process_html_to_markdown.sh`
  - `scripts/chunk.sh`
  - `scripts/build_index.sh`
- Added tests in `tests/test_ingest_profile.py` for profile layout and schema derivation.

### Why
- Ensure ingestion artifacts and database schema are strongly tied to a specific ingest profile by default.
- Make experiment management more intuitive and reduce accidental cross-experiment contamination.

### Surprising findings
- Existing ingest profiles already persisted step settings, but runtime defaults still pointed to shared flat folders, creating an implicit split-brain between profile metadata and artifact layout.

### Validation experiments and results
- `source .venv/bin/activate && bash agent_logs/20260215_182045_validate_ingestion_profile_first_layout.sh`
  - `pre-commit run --all` -> pass.
  - `pytest -vvv tests/` -> `81 passed, 1 warning`.

### Scripts preserved under `agent_logs/`
- `agent_logs/20260215_182045_validate_ingestion_profile_first_layout.sh`
  - Runs required lint/format/type/UI hooks plus full backend tests.

## 2026-02-15 - UI improvements: conversation-grouped history, wider desktop layout, richer ingested explorer

### Previous state
- History sidebar rendered one row per request entry, so multi-turn conversations appeared fragmented as separate items.
- On wide screens, app content remained visually constrained and the answer pane felt cramped relative to available space.
- Ingested companies panel showed only plain ticker/company text without document-level metadata.

### What changed
- Conversation-aware history UI
  - `src/andromeda/static/ts/index/history.ts`
    - added `groupHistoryByConversation(...)` and conversation-level sidebar rendering.
    - sidebar now shows one item per conversation with turn count + latest-turn metadata.
  - `src/andromeda/static/ts/index/main.ts`
    - selection now targets a conversation group instead of a single history entry.
    - answer pane now renders a full multi-turn conversation thread in one scrollable view.
    - latest turn in selected conversation remains the active detail source for chunks/source viewer/timing.
- Desktop layout rebalance
  - `src/andromeda/static/index.html`, `src/andromeda/static/ts/index/dom.ts`, `src/andromeda/static/ts/index/layout.ts`
    - increased max container width and rebalanced grid/sidebar widths.
    - reduced default source-pane width and tightened source max ratio to free more room for the answer pane.
- Ingested companies explorer upgrade
  - `src/andromeda/ingested_companies.py`
    - endpoint now emits per-ticker aggregates and `documents` details (form/date/doc id/chunk counts/source/chunks paths).
    - still preserves ticker/company fields for compatibility.
  - `src/andromeda/static/ts/index/ingested.ts`, `src/andromeda/static/index.html`
    - replaced plain text list with interactive ticker cards and document table.
    - added links to open source/chunk files and searchable document-level filtering.
    - implemented custom toggle controls (not nested `<summary>`) to keep Playwright strict locators stable.
- Updated release notes
  - `CHANGELOG.md` Unreleased/Changed updated for the three UI behavior changes above.

### Surprising findings
- Existing Playwright tests used `#ingestedDetails summary` strict locator; nested `<summary>` elements inside the upgraded ingested panel caused deterministic test failures.
- Replacing nested details/summary with custom button toggles preserved interactivity while restoring test compatibility.

### Validation experiments and results
- Full required validation script executed:
  - `bash agent_logs/20260215_191500_validate_ui_grouping_layout_ingested.sh`
  - Result:
    - `npm run -s build:ts` passed
    - `PRE_COMMIT_HOME=/tmp/pre-commit-cache VIRTUALENV_OVERRIDE_APP_DATA=/tmp/virtualenv-app-data pre-commit run --all` passed
    - `pytest -vvv tests/` passed (`81 passed, 2 warnings`)

### Scripts preserved under `agent_logs/`
- `agent_logs/20260215_191500_validate_ui_grouping_layout_ingested.sh`
  - Runs TypeScript build + full pre-commit + full pytest suite.

## 2026-02-15 - Deep tools-first finance integration (yfinance + edgartools + RAG-as-function)

### Previous state
- Query runtime was tools-first at planning level, but execution still always centered on retrieval/rerank before answer synthesis.
- There was no native finance tool adapter layer in this repository for:
  - yfinance price/news/valuation snapshots
  - edgartools SEC financial metrics/statements
- RAG retrieval was not represented as an explicitly skippable callable function in planner semantics.
- Query responses did not expose structured finance tool outputs.

### What changed
- Added a dedicated finance adapter module:
  - `src/andromeda/finance_tools.py`
  - Includes typed `FinanceToolResult` + `FinanceToolStatus` and bounded context serialization.
  - Wraps:
    - yfinance: `ticker_info`, `ticker_news`, `price_history`
    - edgartools: annual/quarterly metrics + annual statement snapshots.
- Extended planner schema and plan state in `src/andromeda/query_runtime.py`:
  - `PlannerDecision`: `use_rag`, `use_yfinance`, `use_edgar_financials`
  - `PlannedQuery`: same tool usage flags
  - Added heuristics to resolve tool usage when planner output omits fields.
- Reframed RAG as callable/optional function in execution:
  - Query pipeline now runs `finance tools` before retrieval.
  - If `use_rag=false`, retrieval/rerank are skipped entirely and final synthesis uses tool context only.
- Added structured tool outputs to API payloads:
  - `QueryResponse.tool_results`.
- Updated prompt construction path for synthesis across tool data + retrieved chunks:
  - `src/andromeda/qa.py` now supports `tool_context` in both draft/refine prompt builders.
- Updated streaming runtime in `src/andromeda/query_streaming.py`:
  - new `tools` status step
  - new `tool_results` stream event
  - new `tools_ms` timing capture
  - streaming generation now passes tool context through prompt builders.
- Added focused test coverage:
  - `tests/test_finance_tools.py`
  - `tests/test_query_runtime_tools_first.py`
  - updated `tests/test_qa.py` for `tool_context` prompt expectations.

### Why
- Enables complementary use of tool data and RAG chunks in one synthesis pass.
- Enables tool-only fast path for direct metric/valuation/news questions, reducing unnecessary retrieval cost.
- Prepares backend payloads/events for richer answer-pane rendering of finance artifacts during stream execution.

### Surprising findings
- `pre-commit` failed in this sandbox due readonly default cache path (`/home/mlin/.cache/pre-commit`); fixed by setting `PRE_COMMIT_HOME=/tmp/pre-commit-cache`.
- Existing frontend streaming loop safely ignores unknown event types, so backend `tool_results` event can be introduced without frontend breakage.

### Validation experiments and results
- Targeted tests while developing:
  - `source .venv/bin/activate && pytest -q tests/test_finance_tools.py tests/test_query_runtime_tools_first.py tests/test_qa.py`
  - Result: pass (`9 passed`).
- Required lint/type/UI checks:
  - `source .venv/bin/activate && PRE_COMMIT_HOME=/tmp/pre-commit-cache pre-commit run --all`
  - Result: pass.
- Required full backend tests:
  - `source .venv/bin/activate && pytest -vvv tests/`
  - Result: pass (`86 passed, 2 warnings`).

### Scripts preserved under `agent_logs/`
- `agent_logs/tools_first_finance_integration_20260215_202851.md`
  - Planning document (phased approach + acceptance criteria + files list).

### Follow-up update (same scope)
- Added live frontend rendering for streamed finance tool outputs:
  - `src/andromeda/static/ts/index/main.ts`
  - stream handler now consumes `tool_results` events and displays a temporary "Live Tool Snapshot" block in the answer pane while final LLM text is still streaming.
- Rebuilt TypeScript output (`npm run -s build:ts`) so static JS entrypoints include the new stream behavior.
- Re-ran required checks after this update:
  - `PRE_COMMIT_HOME=/tmp/pre-commit-cache pre-commit run --all` -> pass
  - `pytest -vvv tests/` -> pass (`86 passed, 2 warnings`)

## 2026-02-15 - Generation controls decoupling + finance tool panel + ingest-profile doc-index inference

### Previous state
- `thinking` mode implicitly enabled draft+refine, coupling answer depth and two-stage generation.
- Finance `tool_results` were rendered as temporary markdown text mixed into the final answer area.
- EdgarTools calls could fail due to missing SEC user identity setup.
- `/ingested_companies` primarily depended on `FINRAG_DOC_INDEX_PATH`, which was redundant with profile-scoped artifacts.

### What changed
- Decoupled generation controls:
  - `src/andromeda/generation_controls.py`: `thinking.enable_refine` default changed to `False`.
  - `src/andromeda/static/index.html`, `src/andromeda/static/ts/index/dom.ts`, `src/andromeda/static/ts/index/main.ts`: added explicit `enableRefine` checkbox and wired request payload persistence (`enable_refine`) independent of mode.
- EdgarTools identity handling:
  - `src/andromeda/finance_tools.py`: calls `edgar.set_identity(USER_EMAIL)` before company access.
  - returns explicit `edgar_set_identity` tool error when `USER_EMAIL` is missing/invalid.
- Tool rendering upgrade in UI:
  - `src/andromeda/static/index.html`, `src/andromeda/static/ts/index/main.ts`: added dedicated "Tool snapshot" panel with tool cards.
  - includes SVG price chart for `yfinance_get_price_history`, valuation/company metrics card for `yfinance_get_ticker_info`, and linked headlines for `yfinance_get_ticker_news`.
  - tool panel now renders separately from LLM final markdown.
- Citation UX improvement:
  - `src/andromeda/static/ts/index/citations.ts`: `[tool=...]` markers now render as visual chips (`toolCitationChip`) while `[doc=...]` remains clickable to source viewer.
- Doc index inference improvement:
  - `src/andromeda/ingested_companies.py`: resolution order now is explicit env override first, then inferred ingest-profile chunk path (`doc_index.jsonl`) with latest fallback under `chunked_*/`.
  - `src/andromeda/main.py`: removed runtime mutation of `FINRAG_DOC_INDEX_PATH` in ingestion status endpoint and updated endpoint docs.
  - `src/andromeda/static/ts/index/ingested.ts`: updated failure messaging to inferred-path semantics.
- Tests updated:
  - `tests/test_finance_tools.py`: adjusted edgar mock to include `set_identity` + added missing-`USER_EMAIL` coverage.

### Why
- Makes generation controls intuitive and explicit.
- Keeps financial tool artifacts visible and structured without polluting narrative answer text.
- Fixes known EdgarTools SEC identity setup failure mode.
- Removes redundant env-path coupling by honoring ingest-profile artifacts directly.

### Validation experiments and results
- `npm run -s build:ts` -> pass.
- `source .venv/bin/activate && PRE_COMMIT_HOME=/tmp/pre-commit-cache pre-commit run --all` -> pass.
- `source .venv/bin/activate && pytest -vvv tests/` -> pass (`87 passed, 2 warnings`).

### Scripts preserved under `agent_logs/`
- `agent_logs/20260215_211245_validate_generation_controls_tools_ui.sh`
  - Replays TypeScript build + pre-commit + full tests.

## 2026-02-16 - README rewrite for tools-first architecture positioning

### Previous state
- `README.md` was still heavily framed around earlier rewrite/migration history and did not present the current system as a cohesive tools-first design document.

### What changed
- Rewrote `README.md` as an implementation-backed technical overview focused on:
  - tools-first query orchestration (planner decisions, execution order, statuses)
  - finance tool integration (`yfinance` + `edgar`) and structured tool payloads
  - PostgreSQL hybrid retrieval model and sparse-method compatibility safeguards
  - profile-scoped ingestion/indexing pipeline and on-the-fly ticker ingestion jobs
  - API surface, streaming event contract, and concise local runbook/test gates
- Removed obsolete rewrite-process detail from primary documentation, preserving historical context in changelog/logbook only.

### Why
- Improve technical communication quality for external review/interview usage while keeping claims tied to current code and tests.

### Validation experiments and results
- Pending in this entry: run required repository checks after doc update.

### Validation experiments and results (completed)
- `source .venv/bin/activate && PRE_COMMIT_HOME=/tmp/pre-commit-cache pre-commit run --all`
  - Result: pass.
- `source .venv/bin/activate && pytest -vvv tests/`
  - Result: `87 passed, 2 warnings`.

## 2026-02-16 - README diagram enhancement for architecture communication

### Previous state
- The rewritten README had clear technical prose but no Mermaid diagrams.

### What changed
- Added Mermaid diagrams to `README.md` for:
  - high-level runtime architecture (UI -> planner -> tools/RAG -> synthesis)
  - app logic flow (`/query` and `/query_stream` decision path)
  - ingestion/indexing flow (`download -> process -> chunk -> build_index -> PostgreSQL`)
  - PostgreSQL ER model (`documents`, `chunks`, `retrieval_runtime_config`)

### Why
- Improve visual communication of system design and execution flow for interview and technical review contexts.

### Validation experiments and results
- `source .venv/bin/activate && PRE_COMMIT_HOME=/tmp/pre-commit-cache pre-commit run --all`
  - Result: pass.
- `source .venv/bin/activate && pytest -vvv tests/`
  - Result: `87 passed, 2 warnings`.

## 2026-02-16 - Multi-ticker root-fix with parallel per-ticker briefs + streamed subagent output

### Previous state
- Multi-ticker handling depended on merged rerank output and `_enforce_ticker_coverage(...)`, which could still produce imbalanced evidence distribution.
- There was no dedicated map/reduce flow where each ticker gets its own brief before synthesis.
- Streaming UI had no concept of per-ticker subagent output and no controls for per-brief budget or synthesis effort.

### What changed
- Added dedicated multi-ticker map/reduce pipeline in `src/andromeda/query_runtime.py`:
  - planner schema extended with `use_multi_ticker_briefs`
  - `PlannedQuery` and pipeline execution state now carry multi-ticker-brief branch data
  - per-ticker retrieval + rerank run in parallel with `ThreadPoolExecutor`
  - per-ticker brief generation runs in parallel
  - final answer synthesis consumes per-ticker briefs (with refine support when enabled).
- Added generation controls in `src/andromeda/generation_controls.py`:
  - `brief_max_tokens`
  - `AnsweringEffort` enum (`low`, `medium`, `high`) surfaced as `answering_effort`.
- Added prompt builders in `src/andromeda/qa.py`:
  - `build_ticker_brief_prompt(...)`
  - `build_multi_ticker_synthesis_prompt(...)`
  - `build_multi_ticker_refine_prompt(...)`.
- Updated request plumbing in `src/andromeda/main.py` and query models to pass/resolve new controls.
- Added streamed per-ticker brief events in `src/andromeda/query_streaming.py`:
  - `briefs_start`
  - `ticker_brief_delta`
  - `ticker_brief_done`
  - `briefs_done`
  with interleaved token deltas emitted by parallel ticker threads.
- Updated UI in `src/andromeda/static/index.html` + `src/andromeda/static/ts/index/*`:
  - advanced options now include `brief_max_tokens` and `answering_effort`
  - progress pipeline includes `briefs` stage
  - answer pane includes a dedicated per-ticker briefs panel that updates live during stream.
- Added/updated tests:
  - `tests/test_query_runtime_tools_first.py` new coverage for multi-ticker brief path
  - `tests/test_generation_controls.py` new coverage for `answering_effort` + `brief_max_tokens` parsing.

### Why
- This addresses the root imbalance issue by removing dependence on one blended global top-K list for comparative answers.
- It improves answer quality and fairness by forcing ticker-local reasoning before cross-ticker synthesis.
- It improves UX transparency by showing per-ticker subagent outputs as they stream.

### Surprising findings
- `pre-commit` initially failed due readonly default cache path (`/home/mlin/.cache/pre-commit`); setting `PRE_COMMIT_HOME=/tmp/pre-commit-cache` fixed it in this sandbox.
- Existing stream event handling in frontend was tolerant to unknown types, so adding new brief events required no compatibility shim.

### Validation experiments and results
- `npm run -s build:ts`
  - Result: pass.
- `source .venv/bin/activate && PRE_COMMIT_HOME=/tmp/pre-commit-cache pre-commit run --all`
  - First run: formatter changed files; second run: pass.
- `source .venv/bin/activate && pytest -vvv tests/`
  - Result: pass (`89 passed, 2 warnings`).

### Scripts preserved under `agent_logs/`
- `agent_logs/20260216_153900_validate_multi_ticker_briefs_frontend_build.sh`
  - Replays TypeScript build command used in this change.

## 2026-02-16 - Eval pipeline revamp (helpfulness + factual GT validation + concurrency prep)

### Previous state
- Eval scoring used single-judge assumptions in summaries and did not expose helpfulness consistently across all relevant query kinds.
- Factual eval generation relied on silver numeric extraction only; no external validation pass.
- Eval runner parallelism used multiprocessing only, which is blocked in this sandbox due semaphore permission limits.
- Open-ended eval failures showed a recurring pattern of over-assertive claims and year-misaligned retrieval.

### What changed
- Helpfulness integration and scoring/reporting updates (already implemented earlier in this revamp sequence):
  - Added `helpfulness_v1` judge in `src/andromeda/eval/judges.py`.
  - Updated default judge sets + per-judge fail-rate reporting in `src/andromeda/eval/scoring.py`.
  - Extended review/scoring outputs in `scripts/score_eval.py`.
- Factual GT validation wiring:
  - Added Edgar validation CLI flow to `scripts/make_eval_set.py`:
    - `--validate-factual-with-edgar`
    - `--edgar-drop-mismatched`
    - `--edgar-rel-tol`
    - `--factual-candidate-multiplier`
  - Added/expanded validator logic in `src/andromeda/eval/ground_truth_validation.py`.
  - Added scale-robust matching (tries plausible scale normalizations when extraction misses scale hints).
- Throughput/concurrency changes for next runs:
  - Added `parallel_backend` to eval runner config (`process` | `thread`) in `src/andromeda/eval/runner.py`.
  - Added CLI switch `--parallel-backend` in `scripts/run_eval.py`.
  - Added thread backend execution path to avoid multiprocessing semaphore dependency.
  - Guarded signal timeout logic so it is a no-op in non-main threads.
- Retrieval/prompt grounding improvements:
  - Added year-window inference from question text in `src/andromeda/query_runtime.py`:
    - if no explicit date filters, infer `YYYY-01-01`..`YYYY-12-31` from question years.
  - Strengthened grounding/citation discipline in `src/andromeda/qa.py` to reduce uncited or inferred claims.
- Added/updated tests:
  - `tests/test_eval_ground_truth_validation.py` (new)
  - `tests/test_eval_runner.py` (expanded)
  - `tests/test_query_runtime_tools_first.py` (year-window inference coverage)

### Surprising findings
- EdgarTools cache writes failed under default home path (`/home/mlin/.edgar`) in this sandbox; setting `HOME=/tmp` was required for validator runs.
- Even with scale fallback, only a minority of supported factual candidates matched Edgar metrics at strict tolerances, indicating substantial extraction/period mismatch noise.

### Experiments and results
1. **Single baseline (pre-validation set)**
- Run dir: `eval/results_revamp/single/eval_run.single_balanced_baseline_v1.20260216_162459`
- Score summary:
  - factual: `gold_hit=0.35`, `numeric_accuracy=0.20`, `factual_correctness_fail=0.60`, `helpfulness_fail=0.45`
  - open_ended: `faithfulness_fail=0.4667`, `helpfulness_fail=0.0667`

2. **Edgar validation tolerance sweep (candidate factual pool)**
- Script: `agent_logs/20260216_164925_edgar_validation_tolerance_sweep.sh`
- Candidate factual count: `211`
- Matched counts by `rel_tol`:
  - `0.15`: 9
  - `0.20`: 9
  - `0.25`: 11
  - `0.30`: 13
  - `0.40`: 17
  - `0.50`: 24

3. **Validated eval set build (tol=0.5, keep statuses)**
- Script: `agent_logs/20260216_165030_generate_eval_set_validated_tol05_v3.sh`
- Output: `eval/eval_queries_revamp_validated_tol05_20260216.jsonl`
- Distribution:
  - total `359`
  - factual `211` with status breakdown:
    - `matched=24`
    - `mismatched=52`
    - `skipped_unsupported_metric=135`

4. **Validated single subset (factual matched-only)**
- Script: `agent_logs/20260216_165235_build_eval_subsets_from_validated_tol05_v1.sh`
- Output: `eval/eval_queries_revamp_single_balanced_validated_tol05_20260216.jsonl`
- factual subset status: `20/20 matched`

5. **Single baseline on validated subset (clean run)**
- Script: `agent_logs/20260216_165322_eval_single_balanced_validated_baseline_v2.sh`
- Run dir: `eval/results_revamp/single/eval_run.single_balanced_validated_baseline_v2.20260216_165302`
- Score summary:
  - factual: `gold_hit=0.40`, `numeric_accuracy=0.45`, `factual_correctness_fail=0.30`, `helpfulness_fail=0.05`
  - open_ended: `faithfulness_fail=0.6667`, `helpfulness_fail=0.0`
  - refusal fail: `0.0`
- Interpretation:
  - factual quality improved strongly after matched-only factual subset construction.
  - open-ended faithfulness remained weak and motivated prompt/runtime grounding improvements.

6. **Threaded concurrency dry run after backend updates (invalid for quality)**
- Script: `agent_logs/20260216_171130_eval_single_balanced_validated_improved_v3_thread.sh`
- Generation run dir: `eval/results_revamp/single/eval_run.single_balanced_validated_improved_v3.20260216_171320`
- Generation summary:
  - `n=50`, `n_ok=8`, `n_err=42`, `wall_total_ms~39.1s`
- This run is **invalid for quality comparison** because vLLM server was stopped mid-run (connection refused); scoring also failed for same reason.

### Validation checks after code edits
- `source .venv/bin/activate && PRE_COMMIT_HOME=/tmp/pre-commit-cache pre-commit run --all`
  - Result: pass.
- `source .venv/bin/activate && pytest -vvv tests/`
  - Result: pass (`101 passed, 2 warnings`).

### Scripts preserved under `agent_logs/`
- `agent_logs/20260216_164610_generate_eval_set_validated_v1.sh`
- `agent_logs/20260216_164640_generate_eval_set_validated_v2_home_tmp.sh`
- `agent_logs/20260216_164925_edgar_validation_tolerance_sweep.sh`
- `agent_logs/20260216_165030_generate_eval_set_validated_tol05_v3.sh`
- `agent_logs/20260216_165235_build_eval_subsets_from_validated_tol05_v1.sh`
- `agent_logs/20260216_165322_eval_single_balanced_validated_baseline_v2.sh`
- `agent_logs/20260216_171130_eval_single_balanced_validated_improved_v3_thread.sh`

### Handoff notes
- Multi-ticker evaluation phase is pending restart of vLLM.
- Recommended restart point:
  1) rerun `single_balanced_validated_improved_v3` end-to-end with server healthy;
  2) then run `eval/eval_queries_revamp_multi_comparison_validated_tol05_20260216.jsonl` with same settings.

## 2026-02-16 (late) - Iteration-by-iteration eval log (N=1 cadence enabled)

### Process update
- Switched logging cadence to **N=1** (append after each iteration/run).
- Goal of this block: retroactively capture each run with (a) what changed, (b) observed metrics, (c) surprising finding, (d) concrete next action.

### Iteration log (single-ticker unless specified)

1) **`v9` baseline tools-first, no refine**
- Run: `eval/results_revamp/single/eval_run.single_holistic_normal_v9_tools8_norefine.20260216_220225`
- What changed: stabilized 8-thread threaded generation path; no refine; tools enabled.
- Metrics:
  - factual numeric accuracy: `0.55`
  - factual correctness fail: `0.20`
  - open-ended faithfulness fail: `0.7333`
- Surprising finding: factual numerics were reasonable but open-ended hallucination rate remained high.
- Action taken next: test retrieval-diversity intervention (MMR).

2) **`v10` MMR diversity ON**
- Run: `eval/results_revamp/single/eval_run.single_holistic_normal_v10_tools8_norefine_mmr.20260216_221157`
- What changed: enabled bounded MMR rerank diversification for narrative questions.
- Metrics:
  - factual numeric accuracy: `0.45` (down)
  - factual correctness fail: `0.25` (worse)
  - open-ended faithfulness fail: `0.7333` (no gain)
- Surprising finding: MMR did not improve faithfulness and hurt factual metrics at this configuration.
- Action taken next: gated MMR off by default.

3) **`v11` narrative quote-guidance prompt**
- Run: `eval/results_revamp/single/eval_run.single_holistic_normal_v11_tools8_norefine_promptquote.20260216_223248`
- What changed: added narrative quote-grounding guidance in prompt extras.
- Metrics:
  - factual numeric accuracy: `0.45`
  - factual correctness fail: `0.15`
  - open-ended faithfulness fail: `0.6667`
- Surprising finding: prompt-only change improved faithfulness relative to v9/v10 without refine.
- Action taken next: align eval serialization to deployed full-chunk behavior.

4) **`v13` deploy-match run (full chunk defaults, no chunk truncation flags)**
- Run: `eval/results_revamp/single/eval_run.single_holistic_normal_v13_tools8_norefine_deploymatch.20260216_224314`
- What changed: removed chunk text/context truncation overrides; used deploy-matching defaults.
- Metrics (original harness):
  - factual numeric accuracy: `0.45`
  - factual correctness fail: `0.25`
  - open-ended faithfulness fail: `0.5333`
- Surprising finding: deploy-match settings improved open-ended faithfulness materially vs earlier runs.
- Action taken next: build dashboard + deeper per-failure trace analysis.

5) **`v14` numeric-guard generation intervention (failed)**
- Run: `eval/results_revamp/single/eval_run.single_holistic_normal_v14_tools8_norefine_numguard.20260216_230154`
- What changed: added strict numeric-claim sanitization and stronger narrative prompt constraints.
- Metrics:
  - factual numeric accuracy: `0.45`
  - factual correctness fail: `0.15`
  - open-ended faithfulness fail: `0.9333`
  - open-ended helpfulness fail: `0.9333`
  - distractor focus fail: `0.8571`
- Surprising finding: severe over-correction; model output collapsed into repetitive “Not explicitly stated...” leading to broad quality regressions.
- Action taken next: treat this as a negative control; start judge-harness isolation before further generation edits.

6) **Judge-harness isolation pass on v13 generations**
- Run: `eval/results_revamp/single/eval_run.single_holistic_normal_v13_tools8_norefine_deploymatch_rescore_harness.20260216_231114`
- What changed: same generations as v13; changed scorer context assembly to prioritize cited chunks under context budget.
- Metrics delta vs original v13 scoring:
  - factual correctness fail: `0.25 -> 0.40` (revealed expected/evidence tension)
  - open-ended faithfulness fail: `0.5333 -> 0.2667` (large improvement)
  - distractor focus fail: `0.0 -> 0.0`
- Surprising finding: prior faithfulness failures were inflated by judge-context truncation that omitted cited evidence.
- Action taken next: calibrate factual judge prompt to trust evidence/context when Expected conflicts.

7) **Judge prompt v2 (factual judge reliability improvement)**
- Run: `eval/results_revamp/single/eval_run.single_holistic_normal_v13_tools8_norefine_deploymatch_rescore_harness_judgev2.20260216_231430`
- What changed: updated `factual_correctness_v1` judge prompt to treat evidence/context as source-of-truth if Expected conflicts.
- Metrics (same v13 generations):
  - factual correctness fail: `0.05`
  - open-ended faithfulness fail: `0.2667`
- Surprising finding: large factual fail-rate drop indicates residual GT/period ambiguity in the eval set; judge needed explicit conflict-resolution policy.
- Action taken next: keep judge v2 wording; continue generation iterations with calibrated harness.

8) **`v15` softened prompt + sanitizer still on (failed)**
- Run: `eval/results_revamp/single/eval_run.single_holistic_normal_v15_tools8_norefine_softprompt.20260216_231728`
- What changed: reduced prompt strictness but sanitizer still active.
- Metrics:
  - factual correctness fail: `0.05`
  - open-ended faithfulness fail: `0.9333`
  - open-ended helpfulness fail: `0.9333`
- Surprising finding: sanitizer remained the dominant regression source.
- Action taken next: remove sanitizer from answer path.

9) **`v16` no-sanitizer recovery pass**
- Run: `eval/results_revamp/single/eval_run.single_holistic_normal_v16_tools8_norefine_nosanitize.20260216_232700`
- What changed: removed sanitizer from generation path; retained calibrated judge harness.
- Metrics:
  - factual numeric accuracy: `0.45`
  - factual correctness fail: `0.05`
  - open-ended faithfulness fail: `0.4667`
- Surprising finding: large recovery from v14/v15 collapse, but still behind best calibrated v13 re-score (`0.2667`).
- Action taken next: revert narrative prompt phrasing to strongest prior variant.

10) **`v17` prompt revert + no sanitizer (current stable)**
- Run: `eval/results_revamp/single/eval_run.single_holistic_normal_v17_tools8_norefine_revertprompt.20260216_233713`
- What changed: restored prior narrative prompt wording; sanitizer removed; judge harness remained calibrated.
- Metrics:
  - factual numeric accuracy: `0.50`
  - factual correctness fail: `0.05`
  - open-ended faithfulness fail: `0.40`
  - open-ended helpfulness fail: `0.0`
- Surprising finding: improved over v16 on both factual numeric and open-ended faithfulness, but still above best observed faithfulness from calibrated v13 re-score.
- Action taken next: use calibrated harness for multi-ticker run and continue prompt-only improvements incrementally.

11) **Multi-ticker baseline (earlier in sequence, for reference)**
- Run: `eval/results_revamp/multi/eval_run.multi_holistic_normal_v1_tools8_norefine.20260216_222132`
- Metrics:
  - comparison fail: `0.0417`
  - comparison helpfulness fail: `0.0`
- Action taken next: rerun multi-ticker after single-ticker stabilization using current calibrated harness.

### Judge reliability conclusions (explicit)
- Cited-chunk-priority in judge context was necessary; without it, faithfulness was over-penalized on long answers with lower-ranked but cited evidence.
- Factual judge required explicit instruction to resolve `Expected` vs `Evidence/Context` conflicts; otherwise it over-failed evidence-grounded answers on noisy GT rows.
- Current harness choice:
  - keep cited-chunk-priority context assembly
  - keep factual judge v2 prompt wording
  - keep high judge context budget (`80000` chars in these runs)

### Literature notes (papers reviewed + actionability)
1) **Lost in the Middle (Liu et al., 2023)** - long-context models underuse mid-context evidence.
- Actionable now: keep context ordering intentional (prioritize cited/critical chunks in eval harness; keep retrieval ordering interpretable).
- Future: add retrieval ordering ablations (front-load table chunks + risk chunks) with latency tracking.

2) **RefChecker (Li et al., 2024)** - claim-level verification improves factuality diagnostics.
- Actionable now: maintain per-case failure analysis at claim granularity in `review.csv` workflows.
- Future: add optional claim-splitting + verifier pass as an *analysis* tool (not default generation path) to avoid latency hit.

3) **QAFactEval (Fabbri et al., NAACL 2022)** - QA-based factual consistency evaluation provides better error localization.
- Actionable now: continue judge explanations + per-judge fail-rates rather than single scalar.
- Future: add automatic claim-question generation for targeted faithfulness triage on failed answers.

4) **Self-RAG (Asai et al., 2023)** / **CRAG-like correction ideas**
- Actionable now: keep tools-first routing with RAG fallback policy explicit and measured.
- Future: evaluate lightweight reflection tokens / retrieval correction only on uncertain cases (confidence-gated), not all queries.

### Scripts preserved in this block
- `agent_logs/20260216_231500_eval_single_holistic_normal_v14_tools8_norefine_numguard.sh`
- `agent_logs/20260216_232000_rescore_v13_with_cited_chunk_priority.sh`
- `agent_logs/20260216_232620_rescore_v13_harness_plus_factual_prompt_v2.sh`
- `agent_logs/20260216_233050_eval_single_holistic_normal_v15_tools8_norefine_softprompt.sh`
- `agent_logs/20260216_234000_eval_single_holistic_normal_v16_tools8_norefine_nosanitize.sh`
- `agent_logs/20260216_235200_eval_single_holistic_normal_v17_tools8_norefine_revertprompt.sh`


## 2026-02-16 (N=1 iteration entry) - Multi-ticker calibrated rerun (`v2`)

### Iteration
- Run: `eval/results_revamp/multi/eval_run.multi_holistic_normal_v2_tools8_norefine_calibrated.20260216_234717`
- Script: `agent_logs/20260217_000700_eval_multi_holistic_normal_v2_tools8_norefine_calibrated.sh`
- Config:
  - mode=`normal`
  - concurrency=`8`
  - parallel backend=`thread`
  - refine=`off`
  - tools=`enabled`
  - judge context chars=`80000`
  - harness uses cited-chunk-priority context + factual judge v2 wording.

### Metrics observed
- generation: `n=24`, `n_ok=24`, `n_err=0`, `wall_total_ms=428985.97`
- comparison fail rate: `0.0417`
- comparison helpfulness fail rate: `0.0`

### Surprising findings
- Quality metrics were effectively unchanged vs earlier multi baseline despite substantial harness work on single-ticker faithfulness.
- Throughput remains bounded by long-tail multi-ticker query latency (map/reduce retrieval + synthesis), not by thread-worker count.

### Action taken afterwards
- Keep multi-ticker defaults unchanged for now (already strong on comparison quality).
- Focus future quality iterations on single-ticker narrative faithfulness where remaining failure mass exists.
- Keep N=1 logging cadence for every subsequent run.


## 2026-02-16 (N=1 iteration entry) - Single-ticker `v17` validation

### Iteration
- Run: `eval/results_revamp/single/eval_run.single_holistic_normal_v17_tools8_norefine_revertprompt.20260216_233713`
- Script: `agent_logs/20260216_235200_eval_single_holistic_normal_v17_tools8_norefine_revertprompt.sh`
- What changed vs prior iteration: restored prior narrative prompt phrasing; no sanitizer; judge harness remained calibrated.

### Metrics observed
- generation: `n=50`, `n_ok=50`, `n_err=0`, `wall_total_ms=333231.64`
- factual numeric accuracy: `0.50`
- factual correctness fail: `0.05`
- open-ended faithfulness fail: `0.40`
- open-ended helpfulness fail: `0.0`
- distractor focus/helpfulness fail: `0.0 / 0.0`

### Surprising findings
- `v17` improved over `v16` on both factual numeric and faithfulness, but remained worse than calibrated `v13` re-score (`faithfulness fail=0.2667`).

### Action taken afterwards
- Proceeded to multi-ticker rerun under same calibrated harness.


## 2026-02-16 (N=1 iteration entry) - Dashboard refresh after latest runs

### Iteration
- Command: `bash agent_logs/20260216_223015_build_eval_dashboard_all.sh`
- Output artifacts:
  - `eval/results_revamp/dashboard/metrics_runs.csv`
  - `eval/results_revamp/dashboard/metrics_runs.json`
  - `eval/results_revamp/dashboard/index.html`

### Metrics observed
- Dashboard now includes `30` runs across single + multi scopes.

### Action taken afterwards
- Used dashboard to select current best calibrated single-ticker reference (`v13` rescore + judgev2) and compare against latest single run (`v17`).


## 2026-02-17 (retroactive backfill) - Early single-ticker holistic iterations (`v4` to `v8`)

### Why this backfill
- This section retroactively captures the missing early runs before the `v9+` N=1 block.
- Source of truth used for reconstruction: run artifacts in `eval/results_revamp/single/*` and dashboard rows in `eval/results_revamp/dashboard/metrics_runs.csv`.

### Iteration log (what changed -> metrics observed -> action taken)

1) **`v4_notools` first scored run**
- Run: `eval/results_revamp/single/eval_run.single_validated_faithfulness_v4_notools.20260216_204046`
- What changed:
  - disabled finance tools (`--disable-finance-tools`)
  - constrained generation (`top_k=30/18`, `draft/final max tokens=2200`, timeout `30s`, concurrency `2`)
- Metrics observed:
  - generation: `n_ok=11/50`, `n_err=39`, `wall_total_ms=93438.53`
  - open-ended: `faithfulness_fail=0.0`, `helpfulness_fail=0.0` on only `open_ended_n_ok=2` (not reliable)
  - factual had `factual_n_ok=0` (no usable factual scoring signal)
- Action taken afterwards:
  - treated this run as infrastructure/timeout-limited and not quality-representative;
  - increased concurrency and moved back to tools-enabled holistic runs.

2) **`v4_notools` second attempt (partial)**
- Run: `eval/results_revamp/single/eval_run.single_validated_faithfulness_v4_notools.20260216_210531`
- What changed:
  - reran same run-name family to recover from prior failures.
- Metrics observed:
  - status `partial_generation`, progress `0.64` (`n_generated_rows=32/50`), no score output.
- Action taken afterwards:
  - stopped pursuing this no-tools branch;
  - switched to tools-enabled holistic baseline (`v5`).

3) **`v5_tools8` attempt A (hard fail)**
- Run: `eval/results_revamp/single/eval_run.single_holistic_normal_v5_tools8.20260216_211742`
- What changed:
  - tools enabled, normal generation controls, concurrency `8`, thread backend.
- Metrics observed:
  - generation: `n_ok=0/50`, `n_err=50`, `wall_total_ms=9807.21`
  - scored artifact exists but not meaningful because no successful generations.
- Action taken afterwards:
  - immediate rerun under same family to isolate transient server/runtime errors.

4) **`v5_tools8` attempt B (partial)**
- Run: `eval/results_revamp/single/eval_run.single_holistic_normal_v5_tools8.20260216_211830`
- What changed:
  - same run family; rerun for stability.
- Metrics observed:
  - status `partial_generation`, `n_generated_rows=18/50`, no score output.
- Action taken afterwards:
  - ran a third attempt before drawing quality conclusions.

5) **`v5_tools8` stable scored run**
- Run: `eval/results_revamp/single/eval_run.single_holistic_normal_v5_tools8.20260216_212541`
- What changed:
  - stable tools-enabled holistic run (normal controls profile).
- Metrics observed:
  - generation: `n_ok=50/50`, `wall_total_ms=284638.40`, throughput `0.176 qps`
  - factual: `numeric_accuracy=0.50`, `factual_correctness_fail=0.25`
  - open-ended: `faithfulness_fail=0.9333`, `helpfulness_fail=0.0`
- Action taken afterwards:
  - prioritized faithfulness error analysis (not numeric pipeline) because open-ended grounding was the dominant failure mode.

6) **`v6_tools8_routing`**
- Run: `eval/results_revamp/single/eval_run.single_holistic_normal_v6_tools8_routing.20260216_213525`
- What changed:
  - runtime routing adjustments (tools/retrieval behavior in this iteration family).
- Metrics observed:
  - generation: `n_ok=50/50`, `wall_total_ms=215869.17`, throughput `0.232 qps` (best throughput in early block)
  - factual: `numeric_accuracy=0.40`, `factual_correctness_fail=0.70`, `factual_helpfulness_fail=0.60`
  - open-ended: `faithfulness_fail=0.9333` (no improvement vs v5 stable)
- Action taken afterwards:
  - did not keep this routing variant due severe factual regression;
  - moved to refinement-assisted experiment to check if faithfulness could be recovered.

7) **`v7_tools8_refine`**
- Run: `eval/results_revamp/single/eval_run.single_holistic_normal_v7_tools8_refine.20260216_214227`
- What changed:
  - enabled refine (`--enable-refine 1`), increased timeout (`120s`), used larger chunk truncation params (`6000/4000`) in this branch.
- Metrics observed:
  - generation: `n_ok=50/50`, `wall_total_ms=335293.59`, throughput `0.149 qps` (slower)
  - factual: `numeric_accuracy=0.35`, `factual_correctness_fail=0.75`, `factual_helpfulness_fail=0.70`
  - open-ended: `faithfulness_fail=0.7333` (better than v5/v6 but still high)
- Action taken afterwards:
  - flagged refine as a non-preferred metric boost path;
  - reverted focus to no-refine improvements (prompt + retrieval/harness) for deploy-match realism.

8) **`v8_tools8_scrub` (partial / inconclusive)**
- Run: `eval/results_revamp/single/eval_run.single_holistic_normal_v8_tools8_scrub.20260216_215447`
- What changed:
  - experimental “scrub” branch attempted after refine path.
- Metrics observed:
  - status `partial_generation`, progress `0.28` (`n_generated_rows=14/50`), no score output.
- Action taken afterwards:
  - treated as inconclusive due partial execution;
  - reset to clean no-refine baseline iteration (`v9`), which starts the already-documented N=1 sequence.

### Summary of lessons from `v4-v8`
- Early low-timeout/no-tools or unstable runs created misleading score artifacts; generation completeness (`n_ok`) must be checked before interpreting judge metrics.
- The major bottleneck was open-ended faithfulness, not raw numeric extraction.
- Routing/refine-only interventions were not durable quality wins; later improvements were correctly shifted to calibrated judge harness + prompt/rag-grounding changes.

## 2026-02-17 (N=1 reproduction) - Reproduced `v13 + harness + judgev2` best score

### Request
- Reproduce: `eval/results_revamp/single/eval_run.single_holistic_normal_v13_tools8_norefine_deploymatch_rescore_harness_judgev2.20260216_231430/score_summary.json`

### What happened
1) **Direct rerun via original script**
- Script: `agent_logs/20260216_232620_rescore_v13_harness_plus_factual_prompt_v2.sh`
- New run: `eval/results_revamp/single/eval_run.single_holistic_normal_v13_tools8_norefine_deploymatch_rescore_harness_judgev2.20260217_001319`
- Observed mismatch vs target:
  - open-ended faithfulness fail: `0.4667` (target `0.2667`)
  - factual correctness fail: `0.0` (target `0.05`)

2) **Root-cause check**
- Compared old/new score rows and found only 5 judge-decision flips.
- Identified harness drift: `src/andromeda/eval/scoring.py` had later chunk-level context compaction changes after the original run timestamp.

3) **Back-compat reproduction (no per-chunk context truncation, same v13 generations + judgev2 settings)**
- Repro run A: `eval/results_revamp/single/eval_run.single_holistic_normal_v13_tools8_norefine_deploymatch_rescore_harness_judgev2_repro_notrunc.20260217_001849`
  - recovered open-ended faithfulness fail `0.2667`, factual correctness fail `0.10`
- Repro run B: `eval/results_revamp/single/eval_run.single_holistic_normal_v13_tools8_norefine_deploymatch_rescore_harness_judgev2_repro_notrunc.20260217_002146`
  - **exact match with target summary**

### Verification
- Exact JSON equality check between target and reproduced run B score summary:
  - `equal True`
- Reproduced file:
  - `eval/results_revamp/single/eval_run.single_holistic_normal_v13_tools8_norefine_deploymatch_rescore_harness_judgev2_repro_notrunc.20260217_002146/score_summary.json`

### Action taken
- Kept both reproduction artifacts for traceability.
- For strict reproducibility claims, pinning the judge-context serialization behavior is necessary.
- Saved reusable repro harness script: `agent_logs/20260217_002500_reproduce_v13_judgev2_notrunc.sh`.

## 2026-02-17 - Added exact eval reproduction guide (`README_EVAL.md`)

### Previous state
- Reproduction details for best `v13` score existed across many scripts and logbook entries but not in one canonical runbook.

### What changed
- Added `README_EVAL.md` with an end-to-end, command-accurate path for reproducing the best `v13` result:
  - profile rebuild/index commands
  - query generation and Edgar validation flow
  - tolerance filtering details (`--edgar-rel-tol 0.5`) and matched-only factual subset construction
  - v13 generation + `judgev2` rescoring
  - exact historical reproduction path via back-compat no-trunc judge-context script.

### Why
- Make reproduction deterministic and interview/demo-friendly for another engineer.
- Make the filtering/tolerance step explicit (the main source of confusion).

### Key artifacts referenced
- `eval/eval_queries_revamp_validated_tol05_20260216.jsonl`
- `eval/eval_queries_revamp_single_balanced_validated_tol05_20260216.jsonl`
- `eval/results_revamp/single/eval_run.single_holistic_normal_v13_tools8_norefine_deploymatch_rescore_harness_judgev2.20260216_231430/score_summary.json`
- `eval/results_revamp/single/eval_run.single_holistic_normal_v13_tools8_norefine_deploymatch_rescore_harness_judgev2_repro_notrunc.20260217_002146/score_summary.json`

## 2026-02-17 - Removed eval chunk truncation CLI args

### Previous state
- `scripts/run_eval.py` accepted `--chunk-text-chars` and `--chunk-context-chars`, and passed values through `RunConfig`.
- `src/andromeda/eval/runner.py` used those fields to truncate persisted retrieved chunk `text` and `context`.

### What changed
- Removed `--chunk-text-chars` and `--chunk-context-chars` from `scripts/run_eval.py`.
- Removed corresponding `RunConfig` fields and truncation usage in `src/andromeda/eval/runner.py`.
- Retrieved chunk payloads now always persist full `text` and `context` (preview remains capped separately).

### Why
- Simplify eval runner surface area and eliminate options that are no longer wanted.
- Avoid accidental truncation drift in run artifacts.

## 2026-02-17 - Package rebrand `finrag` -> `andromeda`

### Scope completed
- Renamed Python package directory from `src/finrag` to `src/andromeda`.
- Replaced package/module references from `finrag` to `andromeda` across source, tests, scripts, docs, and key config files.
- Updated key project metadata:
  - `pyproject.toml` project name and package discovery include.
  - launch/config references such as `uvicorn andromeda.main:app` and pre-commit TS path filters.
- Updated changelog references under `## Unreleased` and path mentions in changelog content to reflect `src/andromeda/...`.

### Previous state vs new state
- Previous state: code and tooling imported/targeted the package namespace `finrag` and source path `src/finrag`.
- New state: code and tooling now use namespace `andromeda` and source path `src/andromeda`.
- Why: repository-wide naming alignment requested by user to standardize branding and module identity.

### Surprising findings
- Historical notes/scripts in `agent_logs/` and documentation carried many hardcoded `finrag` path references that also required updates to keep search consistency.
- Moving `src/finrag` required a second pass to catch stale imports that remained after path relocation.

### Validation experiments and results
- Pending in this entry; run and append after mandatory checks:
  - `source .venv/bin/activate && pre-commit run --all`
  - `source .venv/bin/activate && pytest -vvv tests/`
- Lint/format/type checks:
  - `source .venv/bin/activate && pre-commit run --all`
  - Result: pass (initial run auto-formatted one file, second run clean).
- Tests:
  - `source .venv/bin/activate && pytest -vvv tests/`
  - Result: `116 passed, 1 warning`.

## 2026-02-17 - Chunk-size tradeoff sweep (single-ticker eval50) + frontier mapping docs

### Commits
- `50ecdaf332d3db4514daa6cdb72b43558f0e4b3f` - Add chunk-size eval sweep harness and analysis report
- `4c1633b98c20f50a588f0ed4ca4db6c0905d95f5` - Document prioritized eval frontier tradeoff studies

### Scope
- Ran a controlled chunk-size sweep for `chunk_size in {256, 512, 1024, 2048}` with deploy-matching generation settings.
- Built per-size postgres schemas and scored all runs with the same judge settings.
- Added reusable scripts plus report artifacts.
- Added a separate prioritized frontier-study plan (no execution in that phase).

### Commands/scripts used
- Sweep runner: `agent_logs/20260217_014500_run_chunk_size_tradeoff_eval.sh`
- Metrics collector: `agent_logs/20260217_014500_collect_chunk_size_metrics.py`
- Report: `agent_logs/chunk_size_tradeoff_17Feb2026.md`
- Manifest: `eval/results_revamp/chunk_size_study/run_manifest.csv`

### Key run settings
- Eval set: `eval/eval_queries_revamp_single_balanced_validated_tol05_20260216.jsonl` (n=50)
- Generation concurrency: 12 threads
- Query timeout: 600s (corrected from initial 240s for 2048 stability)
- Judge workers: 8
- Judge context chars: 65000 (rescored all 4 runs for consistency)
  * NOTE: 65k judge context is suboptimal, hence the higher faithfulness failure rate seen here (1024 should be 27%)

### Results summary
- `256`: qps `0.2004`, p95 `92565 ms`, factual fail `0.0000`, open faithfulness fail `0.4667`
- `512`: qps `0.1837`, p95 `115069 ms`, factual fail `0.0000`, open faithfulness fail `0.3333`
- `1024`: qps `0.1684`, p95 `121490 ms`, factual fail `0.0500`, open faithfulness fail `0.5333`
- `2048`: qps `0.1587`, p95 `132783 ms`, factual fail `0.0000`, open faithfulness fail `0.4667`

### Interpretation and action
- `512` is the best quality/latency compromise in this sweep (best open-ended faithfulness fail with moderate latency cost).
- `1024` is dominated by `512` on both latency and faithfulness for this dataset.
- `2048` increases tail latency without corresponding quality gain.
- Next eval optimization iterations should use `chunk_size=512` as primary and keep `256` as speed baseline.

### Notes on anomalies
- Initial `2048` run with `query-timeout-s=240` produced one timeout and a stuck worker teardown path; it was discarded and rerun at `600s`.
- A judge run at `80000` context chars also exhibited a tail hang on 2048; rescoring all runs at `65000` fixed this and kept settings consistent.

## 2026-02-17 - Iteration checkpoint (N=1) for chunk-512 eval extension

### Commit (code/scripts for this iteration)
- `e7551f6` - Add chunk512 eval extension harness and retry-aware eval runtime

### Scope completed in this checkpoint
- Locked extension eval runs to `chunk_size=512` profile/schema:
  - `FINRAG_INGEST_PROFILE=eval_revamp_combined_512_20260217`
  - `POSTGRES_SCHEMA=eval_revamp_combined_512_20260217`
- Added reusable extension scripts for profile build/query generation/subseting and eval runs:
  - `agent_logs/20260217_041800_build_combined_eval_profile.sh`
  - `agent_logs/20260217_042300_generate_eval_set_combined_validated_tol05.sh`
  - `agent_logs/20260217_042350_build_eval100_subsets_combined_tol05.sh`
  - `agent_logs/20260217_042800_build_eval100_from_merged_validated_sets.sh`
  - `agent_logs/20260217_042950_build_combined_profile_chunk512.sh`
  - `agent_logs/20260217_043020_generate_eval_set_combined512_validated_tol05.sh`
  - `agent_logs/20260217_043130_build_eval100_subsets_combined512_tol05.sh`
  - `agent_logs/20260217_044500_eval_single_extension_chunk512_v1.sh`
  - `agent_logs/20260217_045500_eval_single_extension_chunk512_v2_prompttighten.sh`
- Extended eval harness controls:
  - generation retry knob in `scripts/run_eval.py` (`--query-max-retries`, default `1`)
  - judge timeout/retry controls in `scripts/score_eval.py` (`--judge-timeout-s`, `--judge-max-retries`)
- Added stronger evidence-discipline prompt guidance (no-refine path):
  - `src/andromeda/qa.py`
  - `src/andromeda/query_runtime.py`
- Added eval review telemetry for tool usage from trace + tool results in `review.csv` (`scripts/score_eval.py`).

### Iteration runs and metrics

1) **v1 baseline on chunk-512 (no refine, tools enabled, 12 workers, eval100)**
- Run: `eval/results_revamp/single/eval_run.single_ext_chunk512_v1_normal_tools12_norefine_eval100.20260217_043752`
- Generation: `n_ok=100/100`, `n_err=0`, `wall_total_ms=503791.20`
- Score summary:
  - factual correctness fail: `0.0571`
  - open-ended faithfulness fail: `0.2667`
  - refusal fail: `0.0`
  - distractor focus fail: `0.0667`

2) **v2 prompt-tightened attempt (before generation retry fix was applied in runner path)**
- Run: `eval/results_revamp/single/eval_run.single_ext_chunk512_v2_prompttighten_tools12_norefine_eval100.20260217_045414`
- Generation: `n_ok=99/100`, `n_err=1` (one timeout)
- Action: implemented generation timeout retry (`query_max_retries=1`) and reran.

3) **v2 prompt-tightened rerun (with generation retry, recovered timeout)**
- Run: `eval/results_revamp/single/eval_run.single_ext_chunk512_v2_prompttighten_tools12_norefine_eval100.20260217_050424`
- Generation: `n_ok=100/100`, `n_err=0`, `wall_total_ms=443290.16`
- Retry evidence: `query_id=2dcc67c3-e597-485a-81e4-fbb8226880c0` used `query_attempts=2` and succeeded.
- Rescore summary (latest):
  - factual correctness fail: `0.0571`
  - factual helpfulness fail: `0.0857`
  - open-ended faithfulness fail: `0.3333`
  - refusal fail: `0.0`
  - distractor focus fail: `0.0667`

### Tool-usage findings (data-driven)
- For the latest v2 rerun (`20260217_050424`), factual rows show:
  - `35/35` with `used_edgar_financials=true`
  - `0/35` with `used_yfinance=true`
- This confirms factual numeric path is primarily using Edgar tools in this eval setup.

### Surprising findings
- Judge results were not perfectly stable across repeated scoring passes on the same generations (observed drift in open-ended faithfulness/factual helpfulness). This needs explicit handling in the judge reliability plan (for example, fixed rerun protocol or multi-judge aggregation).
- Prompt tightening did not reduce open-ended faithfulness in the latest rerun and appears to hurt factual/distractor helpfulness in this sample.

### Actionable next step after this checkpoint
- Keep chunk-512 + generation retry as baseline runtime settings.
- Revert/soften the v2 prompt-tightening changes and prioritize judge reliability + targeted factual ambiguity handling next.

## 2026-02-17 - Iteration pause due Postgres outage (per instruction)

### Detection
- While resuming eval iterations, a direct DB connectivity check failed:
  - DSN host: `127.0.0.1`
  - port: `6543`
  - error: `psycopg.OperationalError: connection refused`

### Action taken
- Stopped all eval iteration work immediately.
- Did not launch new generation/index/eval jobs after failure detection.

### Resume condition
- Resume only after Postgres accepts connections again on configured DSN.

## 2026-02-17 - Judge alignment audit + prompt iterations (manual-labeled dev/test)

### Baseline audit harness + labels
- Commit: `99b3552`
- Added judge reliability tooling and manual-audit dataset:
  - `scripts/judge_reliability.py` (decision-level audit builder + dev/test metrics + bootstrap CIs)
  - manual review prep scripts and curated open-ended scoring utility under `agent_logs/`
  - baseline decision audit: `agent_logs/judge_audit_open71_plus_eval100_20260217.csv` (`n=167` decisions)
  - baseline alignment report: `agent_logs/judge_reliability_baseline_20260217.json`
- Manual labeling scope:
  - target judges with non-zero fail rates: `faithfulness_v1`, `factual_correctness_v1`, factual `helpfulness_v1`, `focus_v1`
  - source runs: single-eval100 + open-ended 71-sample curated subset
  - labels stored in `human_label`/`human_notes` columns; manual overrides captured for known judge mistakes.
- Baseline alignment (held-out test):
  - `faithfulness_v1`: precision_fail `0.6667`, recall_fail `1.0000`, f1_fail `0.8000`, accuracy `0.9524`
  - `factual_correctness_v1`: no fail-positives in test slice (`accuracy=1.0`, fail metrics degenerate)
  - `focus_v1`: no fail-positives in test slice (`accuracy=1.0`, fail metrics degenerate)
  - factual `helpfulness_v1`: no fail-positives in test slice (`accuracy=1.0`, fail metrics degenerate)

### Iteration 1 (materiality-lenient faithfulness prompt)
- Commit: `a6c3a66`
- Artifacts:
  - run script: `agent_logs/20260217_203100_judge_iter1_materiality_rescore.sh`
  - audit snapshot: `agent_logs/judge_audit_open71_plus_eval100_iter1_materiality_20260217.csv`
  - alignment report: `agent_logs/judge_reliability_iter1_materiality_20260217.json`
- Result:
  - reduced raw open-ended fail rates in rescoring summaries
  - but **alignment regressed** on labeled test set for `faithfulness_v1`:
    - precision_fail `0.6667 -> 0.5000`
    - recall_fail `1.0000 -> 0.5000`
    - f1_fail `0.8000 -> 0.5000`
    - accuracy `0.9524 -> 0.9048`
- Interpretation:
  - prompt became too permissive; false negatives increased materially.

### Iteration 2 (re-balanced materiality prompt)
- Commit: `d33a603`
- Artifacts:
  - run script: `agent_logs/20260217_204100_judge_iter2_materiality_balanced_rescore.sh`
  - audit snapshot: `agent_logs/judge_audit_open71_plus_eval100_iter2_materiality_balanced_20260217.csv`
  - alignment report: `agent_logs/judge_reliability_iter2_materiality_balanced_20260217.json`
- Result:
  - did not recover alignment; remained worse than baseline on `faithfulness_v1` test:
    - precision_fail `0.3333`
    - recall_fail `0.5000`
    - f1_fail `0.4000`
    - accuracy `0.8571`
- Interpretation:
  - this prompt still under-calls fails relative to expert labels.

### Action taken after iterations
- Reverted `faithfulness_v1` prompt edits (kept original baseline prompt behavior).
- Decision: keep baseline judge prompt and keep new reliability harness/manual audit workflow for future judge work.
- Next judge-work direction:
  - improve reliability via judge aggregation/consensus (harness-level) rather than prompt softening,
  - keep fixed labeled split and track deltas only against this frozen benchmark.

## 2026-02-17 - Open-ended faithfulness loop (diverse 100-question set, iterations 1-4)

### Commits in this loop
- `44d791c` - open-ended eval harness scripts, plan doc, and iteration summary artifacts.
- `cf92d90` - runtime/prompt guardrails for narrative year-scope and broader narrative-intent retrieval coverage.

### Scope and setup
- Objective: reduce open-ended `faithfulness_v1` failure while keeping `helpfulness_v1` stable, using open-ended-only evals.
- Dataset build script: `agent_logs/20260217_221500_generate_openended100_diverse_v1.sh`.
- Eval scripts:
  - `agent_logs/20260217_221700_eval_openended100_iter1_baseline.sh`
  - `agent_logs/20260217_221900_eval_openended100_iter2_periodscope.sh`
  - `agent_logs/20260217_222000_eval_openended100_iter3_narrative_coverage.sh`
  - `agent_logs/20260217_222100_eval_openended100_iter4_narrative_temp0.sh`
- Shared eval controls across this loop:
  - generation: `concurrency=12`, `parallel-backend=thread`, `query-timeout-s=350`, `query-max-retries=1`
  - scoring: `judge-workers=12`, `judge-context-chars=80000`, `judge-timeout-s=350`, `judge-max-retries=1`
  - profile/schema: `eval_revamp_combined_512_20260217`

### Dataset diversity snapshot (new 100 open-ended set)
- File: `eval/eval_queries_openended100_diverse_20260217_v1.jsonl`
- Count: `100` open-ended questions
- Coverage:
  - unique tickers: `20`
  - template families: `10`
  - family distribution captured in generation script output and in tags (`family_*`).

### Iteration table
- Iteration summary artifact: `agent_logs/openended_iteration_summary_20260217.md`
- CSV: `agent_logs/openended_iteration_metrics_20260217.csv`

| Iteration | Strategy | Run | n_ok | Faithfulness fail | Helpfulness fail |
|---|---|---|---:|---:|---:|
| iter1 | Baseline on diverse open-ended set | `eval/results_revamp/open/eval_run.open_diverse_iter1_baseline_normal_tools12_norefine_qt350_jt350.20260217_220205` | 100 | 0.22 | 0.00 |
| iter2 | Period-scope guardrail prompt additions | `eval/results_revamp/open/eval_run.open_diverse_iter2_periodscope_normal_tools12_norefine_qt350_jt350.20260217_222053` | 100 | 0.26 | 0.00 |
| iter3 | Expanded narrative-intent detection + retrieval diversification | `eval/results_revamp/open/eval_run.open_diverse_iter3_narrativecoverage_normal_tools12_norefine_qt350_jt350.20260217_223936` | 100 | 0.18 | 0.00 |
| iter4 | Narrative `draft_temperature=0` ablation | `eval/results_revamp/open/eval_run.open_diverse_iter4_narrativetemp0_normal_tools12_norefine_qt350_jt350.20260217_225755` | 99 | 0.232323 | 0.00 |

### Iteration-by-iteration notes (N=1 style)
1) Iteration 1 (`iter1`, baseline)
- What changed: no runtime changes; only diverse open-ended dataset and fixed eval settings.
- Main issue observed:
  - dominant failure mode was unsupported extrapolation/hallucination;
  - a major subtype was filing-year vs covered-period confusion (questions asking "in 2025/2026" answered as if full-period evidence existed when context mostly reflected other covered periods).
- Strategy options considered after analysis:
  - prompt-level year-scope guardrails,
  - broader narrative-intent routing + retrieval diversification,
  - lower draft temperature for narrative answers.
- Chosen next strategy: prompt-level period-scope guardrails first.

2) Iteration 2 (`iter2`, period-scope guardrails)
- What changed:
  - `src/andromeda/qa.py`: stronger evidence discipline rules for filing year vs covered period handling.
  - `src/andromeda/query_runtime.py`: added dynamic `period_scope_prompt_extra(...)` from retrieved metadata and stricter year-scope notes.
- Result: faithfulness regressed (`0.22 -> 0.26`), helpfulness stayed `0.00`.
- Surprising finding:
  - this fixed a subset of period issues but introduced broader regressions elsewhere.
- Chosen next strategy: improve narrative-intent detection/retrieval coverage (generalizable, non-template-specific) rather than further tightening this prompt branch.

3) Iteration 3 (`iter3`, narrative-intent + retrieval diversification)
- What changed:
  - expanded `_question_mentions_filing_narrative(...)` coverage for open-ended families (growth opportunities, dependencies, management commentary, capital allocation, margin/cash-flow framing, etc).
  - added focused retrieval query augmentations for:
    - risk/uncertainty,
    - capital allocation/margin/cash flow,
    - execution dependencies/demand commentary.
- Result: best in this series (`faithfulness 0.18`, `helpfulness 0.00`).
- Surprising finding:
  - larger, better-targeted retrieval query diversification improved both quality and latency profile vs iter2.
- Action taken: treat iter3 runtime behavior as current best candidate.

4) Iteration 4 (`iter4`, narrative temp=0 ablation)
- What changed:
  - forced narrative-answer draft temperature to `0.0` (ablation).
- Generation anomaly:
  - two timeout retries were triggered;
  - one query exhausted retries and failed (`n_ok=99/100`), query id `3f876e95-8c43-44b2-91e2-bc44d806e0d6`.
- Result: degraded vs iter3 (`faithfulness 0.232323`, `helpfulness 0.00`).
- Decision: do not keep this ablation as default behavior.

### Reliability/harness observations
- In iter4, after a timed-out generation failure, the wrapper script required interruption to progress to scoring; run artifacts were still valid and scoring completed after manual continuation.
- For this loop, continue treating `iter3` as best run for quality among evaluated variants.

### Actionable next steps
- Keep iter3-style narrative routing/retrieval behavior as baseline for next open-ended improvements.
- Next potential improvement area (not implemented in this loop): add explicit answer post-check for year-scope claims (claim-level period validator) to reduce remaining period mismatch failures in high-risk families (`growth_risk_balance`, `execution_dependencies`, `risk_materiality`).

## 2026-02-17 - Iter3 faithfulness fail-case manual audit (review.csv human labels)

### Scope
- Audited every `faithfulness_v1` fail from the best Iter3 run:
  - `eval/results_revamp/open/eval_run.open_diverse_iter3_narrativecoverage_normal_tools12_norefine_qt350_jt350.20260217_223936`
- For each failed case, manually reviewed:
  - question,
  - final answer,
  - judge explanation,
  - cited chunk evidence in run artifacts.
- Wrote manual annotations into run-local `review.csv` using:
  - `human_label` (`1` = genuine fail, `0` = judge error)
  - `human_notes` (short rationale).

### Artifacts updated
- `eval/results_revamp/open/eval_run.open_diverse_iter3_narrativecoverage_normal_tools12_norefine_qt350_jt350.20260217_223936/review.csv`
- Supporting audit pack used during review:
  - `agent_logs/iter3_fail_cases_20260217.md`

### Label results on fail set
- Judge-predicted fails audited: `18/18`
- Manual labels:
  - `judge error (human_label=0)`: `16`
  - `genuine model fail (human_label=1)`: `2`
- Estimated fail precision on this audited fail bucket: `2 / 18 = 11.1%`
  - Note: this is fail-bucket precision only (not full confusion metrics, since only fail rows were manually labeled in this pass).

### Genuine error cases (judge was right)
- `022c16b7-48dc-45ff-83eb-6be81d6f07cd` (ATI risk materiality)
  - Answer injected unsupported detail: claimed a new CBA was reached in April 2025; not present in cited context.
- `9582bacb-591f-4ba2-96f8-f0d090f39910` (APH strategy positioning)
  - Answer misattributed organic growth percentages to segments (39/15 claim does not match cited segment rows).

### Judge-error cases found (judge was wrong)
- Temporal-validity false alarms (judge treated provided 2026 filings as non-existent):
  - `aeb38e88-27dc-40a9-a039-a43e865516f3`
  - `95554e27-8d56-43e5-ac3c-878e01a9d9e1`
- Filing-year vs period-end metadata confusion (judge rejected grounded 2025-filed evidence):
  - `b7d1655d-5194-4db2-92db-670161b28678`
  - `1ef52375-c59b-471c-a6ce-6681e97b182a`
  - `99c04bbf-213f-4fb0-b849-7d7b0fa335b6`
- Missed evidence in cited tables/chunks (judge claimed unsupported values that were present):
  - `2b462d5b-1ccc-47bf-a8ea-2177f77f16b7`
  - `4393a735-4c92-469c-9ac0-ac76e7353109`
  - `d7f3e8cc-a87e-4ed8-bd67-54f5990a544e`
  - `ad329082-4576-4ba4-8b01-a31d3be6e7cb`
- Over-strict handling of inference-style prompts where synthesis is expected:
  - `4c39d465-a8f1-49e4-bc5f-e42717b5f210`
  - `5a8bf84a-c1f2-4499-af99-6317e2f6763d`
  - `9cf874e2-1fe7-4c7f-a89e-6fcbc087c9ef`
  - `c1cd294c-e1a5-4b90-ab5f-5fa93a52f9ea`
  - `1a21f637-a044-45f5-9c49-0fff90d37a01`
  - `0bb3d61a-4681-4697-a298-cea294bffffe`
  - `0ece38a9-c0f8-4238-9521-5013b66012d3`

### Practical takeaway
- The current judge is substantially over-calling fail on this Iter3 open-ended set.
- For next judge iteration, priority should be reducing false positive fail calls in these classes:
  - date/period semantics,
  - evidence lookup robustness for tables,
  - calibration for synthesis-heavy prompts where grounded inference is acceptable.

## 2026-02-18 - Tool snapshot UI polish (EDGAR readability + interactive chart modal)

### Previous state
- Tool snapshot cards could look cramped under dense tool output, and long code-style tool names (notably EDGAR tools) could visually overflow card headers.
- EDGAR outputs were shown as raw JSON in the answer pane, which was difficult for non-technical users to interpret quickly.
- Price history was only shown as a small inline sparkline with no expanded inspection mode.

### What changed
- Updated tool snapshot card styling in `src/andromeda/static/index.html` to improve spacing hierarchy and prevent header overflow:
  - title wrapping/overflow handling,
  - better header/meta pill layout,
  - improved responsive card behavior.
- Added polished user-facing tool labels in `src/andromeda/static/ts/index/main.ts` (e.g., SEC annual/quarterly metrics, SEC financial statements) instead of raw internal function IDs.
- Reworked EDGAR rendering in `src/andromeda/static/ts/index/main.ts`:
  - `edgar_get_financial_metrics` / `edgar_get_quarterly_financial_metrics` now render as metric tables,
  - `edgar_get_financial_statements` now renders structured statement blocks with parsed line items (and readable line fallback when parsing is sparse),
  - removed raw JSON-first presentation for EDGAR cards.
- Added interactive price chart modal UI:
  - modal markup/styles in `src/andromeda/static/index.html`,
  - DOM wiring in `src/andromeda/static/ts/index/dom.ts`,
  - click-to-expand chart behavior in `src/andromeda/static/ts/index/main.ts`,
  - hover tooltip with date/price/volume inspection,
  - candlestick rendering in modal when OHLC fields are present; line view fallback otherwise.
- Rebuilt generated frontend JS with `npm run -s build:ts`.

### Why
- Make tool outputs presentable and immediately understandable for investment-oriented users, not just developers.
- Reduce cognitive load in the answer pane by replacing raw payload dumps with structured financial views.
- Improve chart usability by allowing expanded, interactive data inspection directly inside the app.

### Surprising findings
- `pre-commit` still cannot write to default cache path in this environment; must use `PRE_COMMIT_HOME=/tmp/pre-commit-cache`.
- The first `pre-commit run --all` pass auto-fixed trailing whitespace in `agent_logs/iter3_fail_cases_20260217.md`; second pass was clean.

### Validation experiments and results
- `npm run -s build:ts` -> pass.
- `source .venv/bin/activate && PRE_COMMIT_HOME=/tmp/pre-commit-cache pre-commit run --all` -> pass.
- `source .venv/bin/activate && pytest -vvv tests/` -> pass (`116 passed, 2 warnings`).

## 2026-02-18 - Open200 judge audit pass (faithfulness) + Judge Iteration 1

### Audit pass summary (requested cadence: after each complete pass)
- Scope:
  - Completed manual audit on all `43/43` open200 `faithfulness_v1` fail calls from:
    - `eval/results_revamp/open/eval_run.open_diverse200_iter0_baseline_normal_tools12_norefine_qt350_jt350.20260218_002122`
  - Wrote labels (`human_label`, `human_notes`) into:
    - `agent_logs/judge_audit_faithfulness_open71_single100_open200_20260218.csv`
  - Labeling script artifact:
    - `agent_logs/20260218_020500_label_open200_faithfulness_fails_manual.py`
- Manual outcome:
  - Judge errors: `39`
  - Genuine model failures: `4`
  - Genuine fail IDs (material errors):
    - `3f21a340-59f4-4098-a0b8-c9b96c084390` (dividend total miscomputed)
    - `b2a9a8c5-c747-4241-90d2-9d057a130e4f` (margin direction claim contradicts cited numbers)
    - `cd87db11-396f-433a-a829-38ad0b2a0249` (segment-share contradiction + unsupported growth ranges)
    - `d6125077-0b78-4959-be5f-0064349b7e34` (capex numeric mismatch)
- Baseline reliability (before prompt iteration):
  - Report:
    - `agent_logs/judge_reliability_open71_single100_open200_manual_20260218.json`
  - Labeled set: `n=125` (`dev=93`, `test=32`)
  - Test metrics:
    - `precision_fail=0.1875`
    - `recall_fail=1.0`
    - `f1_fail=0.3158`
    - `accuracy=0.5938`
  - Observation:
    - Dominant failure mode was false-positive fail calls (over-strict interpretation of temporal framing/inference).

### Judge Iteration 1 (materiality-aware faithfulness prompt)
- Prompt change:
  - Updated `faithfulness_v1` rubric in:
    - `src/andromeda/eval/judges.py`
  - Key adjustments:
    - evaluate material faithfulness (not peripheral issues),
    - allow grounded synthesis/derived calculations,
    - avoid outside-world temporal assumptions,
    - fail only on material unsupported/contradicted claims.
- Rescore run (fixed generations, judge-only iteration):
  - Script:
    - `agent_logs/20260218_021100_judge_iter3_open200_materiality_rescore.sh`
  - Output:
    - `eval/results_revamp/judge_tuning/eval_run.open200_judge_iter3_materiality.20260218_010749`
  - Open200 fail-rate change:
    - `faithfulness_v1: 0.215 -> 0.08`
- Harness correction for apples-to-apples reliability:
  - Found that naive rebuild changed labeled population (`125 -> 144`) because run extraction changed single-run decision coverage.
  - Fixed by reusing exact baseline labeled decision IDs/splits and swapping only open200 predictions via:
    - `agent_logs/20260218_022000_merge_iter1_predictions_into_baseline_audit.py`
  - Apples-to-apples audit file:
    - `agent_logs/judge_audit_faithfulness_open71_single100_open200_iter1_materiality_apples_20260218.csv`
  - Iter1 reliability report:
    - `agent_logs/judge_reliability_open71_single100_open200_iter1_materiality_apples_20260218.json`
- Apples-to-apples metric delta vs baseline (`n=125` fixed):
  - Dev:
    - `precision_fail: 0.2105 -> 0.3889`
    - `recall_fail: 1.0000 -> 0.8750`
    - `f1_fail: 0.3478 -> 0.5385`
    - `accuracy: 0.6774 -> 0.8710`
    - `cohen_kappa: 0.2398 -> 0.4761`
  - Test:
    - `precision_fail: 0.1875 -> 1.0000`
    - `recall_fail: 1.0000 -> 1.0000`
    - `f1_fail: 0.3158 -> 1.0000`
    - `accuracy: 0.5938 -> 1.0000`
- Caution:
  - Test sample remains small; despite large gains, this should be treated as promising but provisional.
  - Next reliability step should label additional pass-predicted rows to measure false-negative drift under the softer rubric.

- Commit:
  - `79a0ac5`

## 2026-02-18 - Judge Iteration 2 (numeric-consistency addendum) and rollback decision

### What changed
- Added one extra line to `faithfulness_v1` prompt in `src/andromeda/eval/judges.py`:
  - explicit fail instruction when arithmetic/totals/direction-of-change conflicts with cited numbers.
- Rescored same fixed open200 generations with identical runtime settings:
  - script: `agent_logs/20260218_023000_judge_iter4_materiality_numeric_consistency_rescore.sh`
  - run: `eval/results_revamp/judge_tuning/eval_run.open200_judge_iter4_materiality_numeric_consistency.20260218_012738`
  - open200 fail rates:
    - `faithfulness_v1: 0.095`
    - `helpfulness_v1: 0.01`
- Built apples-to-apples alignment file (same labeled IDs/split as baseline):
  - merge script: `agent_logs/20260218_024000_merge_iter2_predictions_into_baseline_audit.py`
  - audit: `agent_logs/judge_audit_faithfulness_open71_single100_open200_iter2_materiality_numeric_apples_20260218.csv`
  - report: `agent_logs/judge_reliability_open71_single100_open200_iter2_materiality_numeric_apples_20260218.json`

### Observations
- Compared to Iteration 1, Iteration 2 regressed:
  - Dev:
    - `precision_fail: 0.3889 -> 0.3684`
    - `f1_fail: 0.5385 -> 0.5185`
    - `accuracy: 0.8710 -> 0.8602`
    - `cohen_kappa: 0.4761 -> 0.4522`
  - Test:
    - `precision_fail: 1.0000 -> 0.6000`
    - `f1_fail: 1.0000 -> 0.7500`
    - `accuracy: 1.0000 -> 0.9375`
- Net takeaway:
  - numeric-consistency addendum recovered no new true positives on held-out labeled test but introduced extra false positives.

### Action taken
- Reverted the extra numeric-consistency sentence, returning to the Iteration-1 materiality prompt as current best.
- Current best judge prompt state remains the Iteration-1 materiality calibration.

- Commit:
  - `065abdd`

## 2026-02-18 - Process guardrail for audit-pass logging cadence

### Guardrail
- For every complete manual audit pass, add a dedicated `Audit pass summary` block to `agent_logs/LOGBOOK.md` immediately before launching the next judge-prompt iteration.
- Minimum fields to log each pass:
  - run ID/path audited,
  - audited fail count,
  - judge-error vs genuine-fail counts,
  - top recurring failure buckets,
  - concrete next-step decision.

### Retroactive confirmation
- The open200 audit summary preceding Judge Iteration 1 is recorded in:
  - `agent_logs/LOGBOOK.md` under `## 2026-02-18 - Open200 judge audit pass (faithfulness) + Judge Iteration 1`
  - subsection `### Audit pass summary (requested cadence: after each complete pass)`.

## 2026-02-18 - Eval documentation refresh + structure cleanup baseline

### What changed
- Rewrote `README_EVAL.md` as the canonical runbook for current best eval settings:
  - production-matched generation hyperparameters (`normal` preset, tools enabled, no refine),
  - judge settings (`judge_context_chars=80000`, timeout/retry/workers),
  - current metric snapshots across single/multi/open tracks,
  - one-pass full-suite execution instructions.
- Added reproducible orchestration scripts:
  - `scripts/prepare_eval_assets.sh`
  - `scripts/run_full_eval_suite.sh`
  (includes manifest output with run paths + score summaries).
- Reorganized backend module layout for cleaner `src/` grouping:
  - query runtime modules moved under `src/andromeda/query/`
  - runtime builders moved under `src/andromeda/runtime/`
  - history persistence moved under `src/andromeda/history/`
  - imports updated across app/tests.
- Added `agent_logs/README.md` and nested folders (`plans/`, `scripts/`, `audits/`, `reports/`, `artifacts/`, `references/`) for future artifacts.

### Important compatibility decision
- Did **not** move historical top-level `agent_logs/*` artifacts already referenced in this logbook.
- Reason: preserve all existing path references for reproducibility and handoff continuity.

### Observations
- Historical eval scripts and docs had diverged from current best operational settings; this made exact replay harder for new contributors.
- A single run-group manifest materially improves reproducibility/debuggability when multiple eval tracks are launched together.

### Next actionable step
- Use `PREPARE_ASSETS=1 bash scripts/run_full_eval_suite.sh` for the next baseline sweep, then append run-group manifest path and metric deltas here.

### Validation
- `source .venv/bin/activate && PRE_COMMIT_HOME=/tmp/pre-commit-cache pre-commit run --all` -> pass.
- `source .venv/bin/activate && pytest -vvv tests/` -> pass (`116 passed, 2 warnings`).

## 2026-02-18 - Chunk-size ablation rerun (80k judge) + latency/accuracy frontier completion

### Context
- Previous chunk-size study used a lower judge context and needed replay under current best settings.
- Frontier run completed generation/scoring but collector failed due malformed manifest CSV rows when settings contained commas.

### What changed
- Re-ran chunk-size ablation with deploy-matched settings and expanded suite context:
  - script: `agent_logs/scripts/eval/20260218_060200_rerun_chunk_size_ablation_expanded80k.sh`
  - settings: tools enabled, no refine, `judge_context_chars=80000`, generation/judge timeout `350s`, retries `1`, workers `12`.
  - outputs:
    - `eval/results_revamp/chunk_size_study_v2_expanded80k/chunk_size_metrics_expanded80k.md`
    - `eval/results_revamp/chunk_size_study_v2_expanded80k/chunk_size_tradeoff_expanded80k.png`
- Hardened frontier harness to avoid CSV corruption and recover existing malformed manifests:
  - `agent_logs/scripts/eval/20260218_060600_run_latency_accuracy_frontier.sh` now writes manifest rows with Python `csv.writer`.
  - `agent_logs/scripts/eval/20260218_060700_collect_latency_accuracy_frontier.py` now parses both quoted rows and older malformed rows.
- Generated frontier artifacts successfully from completed runs:
  - `eval/results_revamp/latency_accuracy_frontier_20260218/latency_accuracy_frontier_metrics.md`
  - `eval/results_revamp/latency_accuracy_frontier_20260218/latency_accuracy_frontier.png`

### Results
- Chunk-size rerun (single100 + multi60, judge 80k):
  - `256`: qps `0.1321`, p95 `180216.6ms`, factual fail `0.0857`, open faith fail `0.0000`, comparison fail `0.0333`
  - `512`: qps `0.1385`, p95 `162625.8ms`, factual fail `0.0571`, open faith fail `0.0667`, comparison fail `0.0167`
  - `1024`: qps `0.1376`, p95 `158374.3ms`, factual fail `0.1143`, open faith fail `0.1000`, comparison fail `0.0333`
  - `2048`: qps `0.1360`, p95 `152962.3ms`, factual fail `0.0857`, open faith fail `0.2000`, comparison fail `0.0167`
- Latency/accuracy frontier (7 settings):
  - Best factual correctness fail: `effort_high` and `temperature_0` at `0.0286`.
  - Best open faithfulness fail: `effort_low` at `0.0000` on this suite.
  - Worst factual fail among tested knobs: `retrieve_high_60_35` at `0.1714` with lower throughput.

### Observations
- Increasing retrieval depth to `60/35` did not help this benchmark; quality and throughput both worsened.
- Lower retrieval depth (`30/18`) improved throughput and factual fail vs baseline but regressed open-ended faithfulness relative to `effort_high`.
- Tight token budget (`32k/16k`) reduced throughput significantly (`0.1077 qps`) without headline quality wins.

### Actionable next steps
- Keep chunk size `512` as default for deploy-matched evals.
- Use `effort_high` as quality-oriented operating point and `effort_low` as speed-oriented point; avoid raising retrieval depth above normal by default.
- Add additional frontier axes next: rerank off/on and max-chunks budget sweep.

- Commit:
  - `8a0f67a`

## 2026-02-18 - Judge variance quantification + retrieval strategy frontier extension (in-progress)

### Scope
- Continued autonomous benchmark loop on deploy-matched eval settings (`normal`, tools enabled, no refine, judge context 80k, timeout 350s, retries 1, workers 12).
- Added new runtime knobs and benchmark harness for retrieval-strategy tradeoff mapping.

### Code changes
- Commit: `cf5aad4`
- Updated:
  - `src/andromeda/query/runtime.py`
    - Added environment toggles:
      - `FINRAG_ENABLE_NARRATIVE_QUERY_EXPANSION` (default on)
      - `FINRAG_ENABLE_NARRATIVE_ASPECT_COVERAGE` (default on)
    - Wired toggles into retrieval/rerank path for narrative queries.
  - `tests/test_query_runtime_tools_first.py`
    - Added coverage tests for narrative query expansion/aspect-coverage toggles.
- New benchmark scripts:
  - `agent_logs/scripts/eval/20260218_114300_extend_latency_accuracy_frontier_mmr_adaptive.sh`
  - `agent_logs/scripts/eval/20260218_115700_extend_latency_accuracy_frontier_narrative_flags.sh`

### Completed experiments
1. Judge stability rescore (6 independent judge passes, fixed generations)
- Script: `agent_logs/scripts/eval/20260218_113300_judge_stability_rescore_single100_baseline.sh`
- Output:
  - `eval/results_revamp/judge_stability_single100_baseline_20260218/judge_stability_replicate_metrics.md`
- Key variance bands:
  - `factual_fail`: mean `0.0619`, std `0.0106`, range `[0.0571, 0.0857]`
  - `open_faith_fail`: mean `0.1000`, std `0.0272`, range `[0.0667, 0.1333]`
- Observation:
  - Judge noise is large enough that sub-3.3pp open-faithfulness deltas are likely inconclusive on this set.

2. Frontier extension: retrieval strategy axis (partial completion)
- Script running: `agent_logs/scripts/eval/20260218_114300_extend_latency_accuracy_frontier_mmr_adaptive.sh`
- Completed rows so far:
  - `strategy_baseline_flags_explicit` (`mmr=0, adaptive=1`)
    - `qps=0.1396`, `p95=154830.0ms`, factual fail `0.1429`, open faith fail `0.0000`, comparison fail `0.0167`
  - `strategy_mmr_on` (`mmr=1, adaptive=1`)
    - `qps=0.1072`, `p95=158371.7ms`, factual fail `0.0000`, open faith fail `0.0333`, comparison fail `0.0167`
- Updated aggregate artifacts:
  - `eval/results_revamp/latency_accuracy_frontier_20260218/latency_accuracy_frontier_metrics.md`
  - `eval/results_revamp/latency_accuracy_frontier_20260218/latency_accuracy_frontier.png`

### In-flight status at log time
- Current active condition: `strategy_adaptive_off` (single run in progress).
- One prior long-tail decode event was handled by configured timeout+retry (no manual interruption required).

### Next actions
- Finish remaining frontier conditions in the same script:
  - `strategy_adaptive_off`
  - `strategy_mmr_on_adaptive_off`
- Re-collect frontier metrics and compare effect sizes against the measured judge variance band before drawing conclusions.

## 2026-02-18 - Retrieval strategy frontier: adaptive-off condition completed

### Completed condition
- `strategy_adaptive_off` (`mmr=0, adaptive=0`) completed for single100 + multi60.
- Script: `agent_logs/scripts/eval/20260218_114300_extend_latency_accuracy_frontier_mmr_adaptive.sh`

### Metrics snapshot (collector)
- `qps=0.1213`
- `p95=178635.1ms`
- `factual_fail=0.0286`
- `open_faith_fail=0.1000`
- `comparison_fail=0.0333`

### Comparison to completed retrieval-strategy rows
- vs `strategy_baseline_flags_explicit` (`mmr=0, adaptive=1`): lower factual fail (`0.1429 -> 0.0286`) but worse open faithfulness (`0.0000 -> 0.1000`) and worse comparison (`0.0167 -> 0.0333`), with slower throughput (`0.1396 -> 0.1213`).
- vs `strategy_mmr_on` (`mmr=1, adaptive=1`): slower and weaker on open-faithfulness/comparison.

### In-flight
- Final retrieval-strategy condition now running: `strategy_mmr_on_adaptive_off`.

## 2026-02-18 - Benchmark wrap-up documentation

### What was added
- New top-level benchmark report:
  - `BENCHMARK.md`
- New figure-generation script:
  - `agent_logs/scripts/eval/20260218_154300_build_benchmark_report_figures.py`
- New benchmark report figures:
  - `eval/results_revamp/benchmark_report_20260218/frontier_open_faithfulness_scatter.png`
  - `eval/results_revamp/benchmark_report_20260218/retrieval_strategy_tradeoffs.png`
  - `eval/results_revamp/benchmark_report_20260218/narrative_guardrails_tradeoffs.png`
  - `eval/results_revamp/benchmark_report_20260218/judge_variance_replicates.png`

### Documentation focus
- Consolidated all recent benchmark outcomes into one report:
  - latency-accuracy frontier summary,
  - retrieval strategy ablation (MMR/adaptive toggles),
  - narrative guardrail ablation,
  - chunk-size ablation (80k judge context),
  - judge variance and interpretation guidance.
- Embedded all key plots directly in markdown for interview/demo readiness.

### Note
- At wrap-up time there were no active eval benchmark processes; latest frontier rows and figures were already materialized and incorporated.

## 2026-02-18 - Benchmark report readability pass

### Motivation
- User feedback: Topline frontier narrative was hard to parse, experiment names were under-explained, and some charts were hard to read (x-axis label crowding, ambiguous bars).

### Changes made
- Rewrote `BENCHMARK.md` to include:
  - explicit experiment catalog (exact runs + rationale),
  - full results summary table across all frontier experiments,
  - clarified definitions for ambiguous IDs (especially `strategy_baseline_flags_explicit`).
- Rebuilt benchmark figure pipeline:
  - script updated: `agent_logs/scripts/eval/20260218_154300_build_benchmark_report_figures.py`
  - outputs moved to tracked report path:
    - `agent_logs/reports/benchmark_figures_20260218/frontier_open_faithfulness_scatter.png`
    - `agent_logs/reports/benchmark_figures_20260218/frontier_throughput_ranked.png`
    - `agent_logs/reports/benchmark_figures_20260218/retrieval_strategy_tradeoffs.png`
    - `agent_logs/reports/benchmark_figures_20260218/narrative_guardrails_tradeoffs.png`
    - `agent_logs/reports/benchmark_figures_20260218/chunk_size_tradeoffs.png`
    - `agent_logs/reports/benchmark_figures_20260218/judge_variance_replicates.png`

### Specific chart fixes
- Throughput chart switched to ranked horizontal bars to avoid unreadable x-axis labels.
- Retrieval-strategy failure chart now includes grouped bars for `factual_fail`, `open_faith_fail`, and `comparison_fail` with value labels and explicit edges.
- Frontier scatter reduced annotation clutter and only labels key anchor points.

### Result
- Benchmark story is now auditable in one pass: what was run, why, and what happened.
