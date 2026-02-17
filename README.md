# Andromeda

Andromeda is a tools-first financial QA system over SEC filings, designed to answer both numeric and narrative investor questions with explicit retrieval evidence and structured tool outputs.

The system is built for production-style constraints:
- local/self-hosted LLMs (vLLM)
- PostgreSQL + pgvector retrieval
- deterministic ingestion/indexing profiles
- eval-driven iteration with reproducible experiment artifacts

## Why This Project Is Interesting

This codebase started as a conventional RAG assistant and was evolved into a production-grade, eval-governed retrieval system:
- planner-routed tools-first execution (yfinance/edgar before RAG when appropriate)
- multi-ticker map/reduce reasoning path
- high-recall retrieval with reranking and metadata-aware filtering
- judge-calibrated evaluation harness with manual-audit alignment workflow

The result is not only better answer quality, but a much stronger engineering story: every major behavior change is backed by experiment artifacts and explicit metric impact.

## Architecture

### Request lifecycle

1. API receives `/query` or `/query_stream`.
2. Conversation state resolves pending clarification context.
3. Planner decides action and tool mix:
   - `answer`
   - `clarification_required`
   - `refused`
   plus `use_rag`, `use_yfinance`, `use_edgar_financials`.
4. Runtime executes tools-first pipeline:
   - finance tool calls
   - optional retrieval/rerank
   - synthesis prompt assembly
   - draft/final generation
5. Response returns:
   - answer text
   - cited chunks
   - structured `tool_results`
   - `tool_trace` execution log

### Core backend modules

- API + wiring:
  - `src/andromeda/main.py`
- Query runtime package:
  - `src/andromeda/query/runtime.py`
  - `src/andromeda/query/streaming.py`
  - `src/andromeda/query/conversation.py`
- Runtime builders/config:
  - `src/andromeda/runtime/builders.py`
- Finance tools:
  - `src/andromeda/finance_tools.py`
- Retrieval/indexing:
  - `src/andromeda/retrieval/retriever.py`
  - `src/andromeda/retrieval/db.py`
- Prompt construction:
  - `src/andromeda/llm/qa.py`
- History persistence:
  - `src/andromeda/history/store.py`
- Eval framework:
  - `src/andromeda/eval/*`
  - `scripts/run_eval.py`, `scripts/score_eval.py`, `scripts/judge_reliability.py`

## Backend Evolution Story (Technical)

### Phase 1: From monolith to modular runtime

Earlier versions concentrated API, orchestration, and helpers in one path.
Refactors separated concerns into:
- query execution package (`query/`)
- runtime construction (`runtime/builders.py`)
- history/source/ingestion services

Impact:
- easier testing of individual execution stages
- cleaner extension points for planner/tooling and streaming behavior

### Phase 2: Tools-first orchestration

The system moved from implicit “RAG-first everything” to explicit planner-routed execution:
- numeric/simple market questions can be handled by tools directly
- narrative SEC questions still use retrieval-backed synthesis
- mixed-mode answers combine both

Impact:
- fewer avoidable numeric hallucinations
- clearer traceability through `tool_trace` and structured tool payloads

### Phase 3: Retrieval quality and latency engineering

Key retrieval improvements:
- profile-scoped indexing and schema isolation
- sparse-method compatibility checks (bm25 vs fts)
- chunk-size tradeoff experiments to choose a better operating point

Observed result from controlled chunk-size study:
- `512` chunks outperformed `1024` on both faithfulness and latency in tested settings

### Phase 4: Eval pipeline as first-class infrastructure

The eval stack was upgraded from ad hoc scoring to a reproducible pipeline:
- helpfulness as a first-class judge across query kinds
- Edgar-backed factual validation during dataset creation
- thread-parallel generation and judge scoring with timeout/retry controls
- decision-level judge reliability audits with manual labels, dev/test splits, and bootstrap metrics

Impact:
- metrics became trustworthy enough to guide roadmap decisions
- regressions are easier to detect and explain

## Evaluation Runbook

See `README_EVAL.md` for:
- canonical answer/judge hyperparameters
- current metric snapshots
- one-pass full-suite run scripts
- query generation lineage (including tolerance filtering)

## Data Pipeline

Ingestion/indexing pipeline:
1. `scripts/download.py`
2. `scripts/process_html_to_markdown.py`
3. `scripts/chunk.py`
4. `scripts/build_index.py`

For eval assets and full-suite orchestration:
- `scripts/prepare_eval_assets.sh`
- `scripts/run_full_eval_suite.sh`

## Local Setup

```bash
cp .env.example .env
source .venv/bin/activate
pip install -e ".[dev]"
npm install
```

Set key env values:
- `POSTGRES_DSN` (or `DATABASE_URL`)
- `OPENAI_CHAT_BASE_URL`
- `OPENAI_EMBED_BASE_URL`
- model names compatible with your hosted endpoints

## Running the App

```bash
source .venv/bin/activate
python -m uvicorn andromeda.main:app --host 0.0.0.0 --port 8000 --reload
```

UI:
- `http://localhost:8000/`

## API Endpoints

- `GET /health`
- `POST /query`
- `POST /query_stream`
- `POST /cancel`
- `POST /ingest`
- `GET /ingest/{job_id}`
- `GET /ingested_companies`
- `GET /source`
- `GET /source_text`
- `GET /history`
- `GET /history_entry`
- `DELETE /history`

## Development Workflow

Use eval and logbook discipline for any quality-impacting change:
- document intent and run script
- record run IDs and metric deltas in `agent_logs/LOGBOOK.md`
- keep reproducible artifacts/scripts under `agent_logs/`

This repository is optimized for “show your work” engineering: design choice -> experiment -> metric delta -> next action.
