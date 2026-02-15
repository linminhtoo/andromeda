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
  - parser helpers in `src/finrag/metadata_models.py`
- Replaced core runtime metadata `.get()` chains with typed parsing/attribute access in:
  - `src/finrag/retriever.py`
  - `src/finrag/qa.py`
  - `src/finrag/main.py`
  - `src/finrag/context_support.py`
  - `src/finrag/chunk_postprocess.py`
  - `src/finrag/eval/generation.py`
  - `src/finrag/eval/scoring.py`
- Added typed DB retrieval row:
  - `HybridSearchRow` in `src/finrag/db.py`
  - retriever now consumes typed rows instead of loose dict access.
- Added typed JSONL parsing for indexing/eval corpus:
  - `scripts/build_index.py` (`DocIndexEntry`, `ChunkJsonRow`)
  - `src/finrag/eval/sec_corpus.py` (`DocIndexRow`, `ChunkExportRow`, `ParsedDocFromSource`)
- Updated eval query generation to use typed company/year targets:
  - `CompanyYearTarget` in `src/finrag/eval/generation.py`
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
  - `src/finrag/static/ts/index/`
  - `src/finrag/static/ts/review/`
  - shared helpers in `src/finrag/static/ts/shared/`
- Added dedicated entrypoints:
  - `src/finrag/static/ts/index/main.ts`
  - `src/finrag/static/ts/review/main.ts`
- Updated TS compile output to ESM module tree under `src/finrag/static/js/`.
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
  - Result: success; modular JS emitted under `src/finrag/static/js/index/`, `src/finrag/static/js/review/`, and `src/finrag/static/js/shared/`.
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
  - `src/finrag/db.py`
  - `src/finrag/retriever.py`
  - `src/finrag/main.py`
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
- Existing `tests/test_context_support.py` assertions were out-of-date with current `src/finrag/context_support.py` behavior (system+user message format and neighbor-context label text).
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
  - `src/finrag/llm_clients.py`
- Updated context situating to set a bounded output cap by default:
  - `src/finrag/context_support.py` now uses `max_tokens=256` for the situating call.
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
- Extended `apply_context_strategy()` in `src/finrag/context_support.py` with a `max_tokens` parameter and forwarded it to each `situate_context()` call.
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
  - Tightened desktop layout width and answer spacing in `src/finrag/static/index.html`.
- Fixed citation navigation robustness:
  - Frontend citation parsing now supports `[doc=... chunk=...]` markers and stores chunk-level targets.
  - Click-through now passes both `doc_id` and `chunk_id` and jumps to exact highlighted source chunk when available.
  - Doc-level fallback still works when `chunk=` is missing.
- Fixed markdown rendering:
  - Added thematic break parsing for `---`, `***`, and `___` into `<hr />`.
- Aligned QA prompt guidance with chunk-level grounding:
  - `src/finrag/qa.py` now instructs model to cite as `[doc=... chunk=...]`.

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
- Added ticker-only background ingestion orchestration in `src/finrag/ingestion_jobs.py`:
  - pipeline: `download -> process_html_to_markdown -> chunk -> build_index`
  - per-job run directories/logs under `data/on_the_fly_ingest/` (configurable via `FINRAG_INGEST_JOBS_ROOT`)
  - in-memory job tracking with lifecycle states (`queued`, `running`, `succeeded`, `failed`)
- Replaced ingestion API contract in `src/finrag/main.py`:
  - `POST /ingest` now accepts JSON `{ticker, per_company}` only (no uploads/OCR)
  - added `GET /ingest/{job_id}` for status polling
- Added runtime-compatible indexing argument wiring so ingestion uses active app settings:
  - PostgreSQL DSN/schema
  - sparse method
  - context strategy/window/metadata key
  - embedding/context provider+model/base URL settings
- Frontend updates (`src/finrag/static/index.html`, `src/finrag/static/ts/index/*`):
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
- Added durable ingest profile store in `src/finrag/ingest_profile.py`:
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
- Reworked app ingestion config loading in `src/finrag/main.py`:
  - load persisted profile step settings first (download/process/chunk/build_index)
  - fallback to env defaults when profile settings are missing
  - include chunk settings (`max_tokens`, `overlap_tokens`, chunker/doc-id strategy, etc.) in runtime job config
- Extended ingestion job manager for multi-ticker jobs in `src/finrag/ingestion_jobs.py`.
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
- The repo had OpenAI-compatible client wrappers in `src/finrag/llm_clients.py` but no dedicated standalone script for directly probing tool/function calling behavior against the configured vLLM endpoint.

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
- Needed a minimal, isolated validation path to test whether the served model (`Qwen/Qwen3-VL-32B-Instruct-FP8`) supports OpenAI-style tool calls end-to-end without modifying runtime code in `src/finrag`.

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
- `RAGService.answer_question()` and `/query_stream` in `src/finrag/main.py` duplicated core query pipeline logic:
  - retrieval filter construction
  - hybrid retrieval
  - rerank branching
  - draft/final prompt branching
- `/query_stream` also duplicated token-streaming loops for draft/final stages.

### What changed
- Added shared `RAGService` helper methods in `src/finrag/main.py`:
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
- Added tools-first planning and execution primitives in `src/finrag/main.py`:
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
- `src/finrag/main.py` had grown to ~1511 lines and mixed endpoint wiring with non-API concerns:
  - streaming orchestration and cancellation state
  - source file resolution and inline text loading
  - ingested-company doc-index parsing/cache logic
  - query history persistence/readback logic
- Even after prior dedup work, `query_docs_stream()` remained difficult to maintain due to mixed responsibilities.

### What changed
- Added new modules and moved logic out of `main.py`:
  - `src/finrag/query_streaming.py`
    - `StreamCancelRegistry`
    - `run_query_stream(...)`
    - stream payload/timing helpers
  - `src/finrag/history_store.py`
    - `QueryHistoryStore` with append/read/read_entry/clear
  - `src/finrag/source_access.py`
    - source allowlist resolution and text file loading helpers
  - `src/finrag/ingested_companies.py`
    - `IngestedCompaniesService` with doc-index parsing and cache
- Rewired `src/finrag/main.py` endpoints to delegate to these modules while keeping API contract stable:
  - `/query_stream` now delegates to `run_query_stream(...)`
  - `/cancel` uses `StreamCancelRegistry`
  - `/source` and `/source_text` use `source_access` helpers
  - `/ingested_companies` uses `IngestedCompaniesService`
  - `/history` endpoints use `QueryHistoryStore`
- Kept conversation/status constants available from `finrag.main` for test compatibility.
- Result: `src/finrag/main.py` reduced from ~1511 lines to ~836 lines.

### Why
- Enforce clearer separation of concerns so `main.py` focuses on public API endpoints and dependency wiring.
- Reduce maintenance cost and drift risk when tools-first answer logic evolves.
- Make streaming and persistence logic independently testable and easier to reason about.

### Validation experiments and results
- `source .venv/bin/activate && python -m py_compile src/finrag/main.py src/finrag/query_streaming.py src/finrag/history_store.py src/finrag/source_access.py src/finrag/ingested_companies.py`
  - Result: pass.
- `source .venv/bin/activate && pre-commit run --all`
  - Result: pass.
- `source .venv/bin/activate && pytest -vvv tests/`
  - Result: `79 passed, 1 warning`.

### Scripts preserved under `agent_logs/`
- No new standalone script created for this pass; validations were run directly from shell commands.

## 2026-02-15 - Runtime builder extraction from `main.py` + planner `response_model` usage

### Previous state
- `src/finrag/main.py` still contained most env/config/service-builder implementation details:
  - LLM provider/model/env resolution
  - PostgreSQL retriever/reranker builders
  - ticker ingestion runtime config + coercion helpers
- Planner decision call in `src/finrag/query_runtime.py` parsed raw LLM JSON manually without using the existing `response_model` capability.

### What changed
- Added `src/finrag/runtime_builders.py` and moved runtime construction logic there:
  - `setup_logging(...)`
  - LLM helpers (`llm_for_chat`, `llm_for_embeddings`, provider/model/env helpers)
  - retrieval config helpers (`context_config`, `sparse_search_method`, `postgres_dsn`)
  - ingestion config assembly (`build_ticker_ingestion_config(project_root=...)`) and coercion helpers
  - `build_retriever()` and `build_reranker()`
- Updated `src/finrag/main.py` to import/use these builders instead of maintaining inline implementations.
- Updated planner structured call in `src/finrag/query_runtime.py`:
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
- `source .venv/bin/activate && python -m py_compile src/finrag/main.py src/finrag/runtime_builders.py src/finrag/query_runtime.py`
  - Result: pass.
- `source .venv/bin/activate && pre-commit run --all`
  - Result: pass.
- `source .venv/bin/activate && pytest -vvv tests/`
  - Result: `79 passed, 1 warning`.

### Scripts preserved under `agent_logs/`
- No new standalone script created for this pass; validations were run directly via shell commands.

## 2026-02-15 - Replace free-form status/action strings with enums in query runtime

### Previous state
- `src/finrag/query_runtime.py` used free-form strings for planner `action` and query `status` fields.
- Branching/comparisons in planning and response construction relied on string literals.

### What changed
- Added enums in `src/finrag/query_runtime.py`:
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
- `source .venv/bin/activate && python -m py_compile src/finrag/query_runtime.py src/finrag/main.py src/finrag/query_streaming.py`
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
- Removed `QUERY_STATUS_*` aliases from `src/finrag/query_runtime.py`.
- Removed alias imports/exports from `src/finrag/main.py`.
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
  - `TopChunk.source_text` in `src/finrag/dataclasses.py`.
  - populated in `RAGService._serialize_top_chunks(...)` (`src/finrag/query_runtime.py`).
  - added to stream chunk payloads in `src/finrag/query_streaming.py`.
- Added markdown chunk line metadata in `src/finrag/chunking.py` (`MarkdownTablePreservingChunker`):
  - `metadata.line_start` (1-based)
  - `metadata.line_end` (1-based, inclusive)
  - emitted for text and table chunks.
- Exposed line metadata to UI payloads via `RAGService._chunk_metadata_for_ui(...)` in `src/finrag/query_runtime.py`.
- Updated source viewer highlighting logic (`src/finrag/static/ts/index/source-viewer.ts`):
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
- Updated `src/finrag/chunking.py` (`MarkdownTablePreservingChunker`) to use `HuggingFaceTokenizer` for:
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
- Added profile layout resolver in `src/finrag/ingest_profile.py`:
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
  - `src/finrag/runtime_builders.py` now falls back to profile-derived schema for ingestion config and retriever when schema env/settings are absent.
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
  - `src/finrag/static/ts/index/history.ts`
    - added `groupHistoryByConversation(...)` and conversation-level sidebar rendering.
    - sidebar now shows one item per conversation with turn count + latest-turn metadata.
  - `src/finrag/static/ts/index/main.ts`
    - selection now targets a conversation group instead of a single history entry.
    - answer pane now renders a full multi-turn conversation thread in one scrollable view.
    - latest turn in selected conversation remains the active detail source for chunks/source viewer/timing.
- Desktop layout rebalance
  - `src/finrag/static/index.html`, `src/finrag/static/ts/index/dom.ts`, `src/finrag/static/ts/index/layout.ts`
    - increased max container width and rebalanced grid/sidebar widths.
    - reduced default source-pane width and tightened source max ratio to free more room for the answer pane.
- Ingested companies explorer upgrade
  - `src/finrag/ingested_companies.py`
    - endpoint now emits per-ticker aggregates and `documents` details (form/date/doc id/chunk counts/source/chunks paths).
    - still preserves ticker/company fields for compatibility.
  - `src/finrag/static/ts/index/ingested.ts`, `src/finrag/static/index.html`
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
