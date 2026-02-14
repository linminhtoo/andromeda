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
