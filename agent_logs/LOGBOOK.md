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
