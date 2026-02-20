# Andromeda

Andromeda is a tools-first financial QA system over SEC filings. It combines planner-routed tool calls, hybrid retrieval, reranking, and eval-governed iteration so numeric and narrative answers are grounded in explicit evidence.

## Latest Status (as of 2026-02-20)

Recent repo changes and benchmark results to know first:

- Planner characteristics quality improved substantially in the latest planner eval run:
  - exact match `0.98`
  - macro F1 `0.9960`
  - micro F1 `0.9919`
  - see `BENCHMARK_PLANNER_v3.md`

## UI Snapshot Walkthrough

### 1) Main workspace (planner + progress + source viewer)

![Andromeda main workspace](docs/full_snapshot.png)

The main UI combines conversation history, planner stage timings, tool results, reranked evidence, and a synchronized source viewer.

### 2) Tools-first evidence collection

![Tool snapshot](docs/tool_snapshot.png)

Tool cards surface profile/valuation, recent news, price history, and SEC financial metrics before final synthesis.

### 3) Reranked chunks used for answer grounding

![Reranked chunks panel](docs/reranked_chunks.png)

The retrieval panel shows ranked chunks, filing metadata, and direct "open source / view in app" links for inspection.

### 4) Final answer structure

![Answer example](docs/answer_example.png)

Answers are organized as thesis points with direct quotes and additional context tied to evidence.

### 5) Citation list for traceability

![Answer citations](docs/answer_citations.png)

Each response includes a consolidated cited-sources block with filing tags and tool outputs.

### 6) Eval review interface

![Eval review UI](docs/eval_review_UI.png)

The review UI supports case filtering, pass/fail labeling, timing inspection, and targeted export/reload workflows.

## Architecture

### Query/Answer Pipeline

```mermaid
flowchart TD
    A[Client / UI] --> B[/POST /query or /query_stream/]
    B --> C[Conversation resolution]
    C --> D[Planner: structured decision]

    D -->|action=clarification_required| E[Return clarifying question]
    D -->|action=refused| F[Return refusal message]

    D -->|action=answer| G[Finance tools stage]
    G --> H{use_rag}
    H -->|no| I[Synthesis prompt with tool context]
    H -->|yes| J[Hybrid retrieval]
    J --> K[Cross-encoder rerank]
    K --> L{multi-ticker briefs}
    L -->|yes| M[Per-ticker briefs + synthesis]
    L -->|no| I
    M --> I

    I --> N[Draft generation]
    N --> O{enable_refine}
    O -->|yes| P[Refine generation]
    O -->|no| Q[Finalize]
    P --> Q

    Q --> R[Persist history + return response]
```

### Retrieval and Reranking Stack

```mermaid
flowchart LR
    Q[User query] --> E[Dense embedding]
    Q --> S[Sparse query branch]

    E --> D[(pgvector dense rank)]
    S --> T[(BM25 or FTS sparse rank)]

    D --> U[Candidate union]
    T --> U
    U --> V[RRF fusion]
    V --> W[Top-k hybrid chunks]
    W --> X[Cross-encoder reranker]
    X --> Y[Top-k reranked chunks]

    Z[Chunk metadata]
    Z -->|retrieval_text / retrieval_context| D
    Z -->|text_for_rerank| X
```

### Ingestion and Indexing Pipeline

```mermaid
flowchart TD
    A[Tickers + profile config] --> B[scripts/download.py]
    B --> C[scripts/process_html_to_markdown.py]
    C --> D[scripts/chunk.py]
    D --> E[Chunk postprocessors]
    E --> F[scripts/build_index.py]

    F --> G[Optional context strategy]
    G --> H[Embedding + retrieval text assembly]
    H --> I[(PostgreSQL schema: documents + chunks)]

    J[/POST /ingest/] --> K[TickerIngestionJobManager]
    K --> B
```

### Eval and Benchmark Loop

```mermaid
flowchart TD
    A[Eval query sets JSONL] --> B[scripts/run_eval.py]
    B --> C[generations.jsonl]
    C --> D[scripts/score_eval.py]
    D --> E[score_summary.json + review.csv]

    F[Planner eval set] --> G[scripts/run_planner_eval.py]
    G --> H[scripts/score_planner_eval.py]

    E --> I[Benchmark reports]
    H --> I
    I --> J[Prompt/runtime/index changes]
    J --> A
```

## Current Design (Backend)

### Planner-first orchestration

- Planner outputs:
  - `action`: `answer`, `clarification_required`, `refused`
  - `characteristics`: `comparison`, `market_data`, `financial_metrics`, `filing_narrative`
  - tool/rag routing hints (`use_rag`, `use_finance_tools`, etc.)
- Clarification vs refusal boundary is explicit and tracked in planner eval artifacts.
- Planner-first routing removed heuristic ticker-inference refusal fallback from the hot path.

Primary module:
- `src/andromeda/query/runtime.py`

### Tools-first answering

- Finance tool adapters (`yfinance`, `edgartools`) run before optional RAG.
- Tool outputs are fed into synthesis prompts and returned in structured payloads.
- Streaming path (`/query_stream`) shares the same planner/tools/retrieval pipeline with stage events.

Primary modules:
- `src/andromeda/finance_tools.py`
- `src/andromeda/query/runtime.py`
- `src/andromeda/query/streaming.py`

### Hybrid retrieval + reranking

- Retrieval backend is PostgreSQL-only (`pgvector` + sparse branch).
- Hybrid search fuses dense and sparse candidates using weighted reciprocal rank fusion.
- Reranker is a cross-encoder over retrieved candidates.
- Metadata-aware retrieval text/context is preserved through chunk export -> indexing -> reranking.

Primary modules:
- `src/andromeda/retrieval/db.py`
- `src/andromeda/retrieval/retriever.py`
- `src/andromeda/processing/metadata_models.py`
- `src/andromeda/processing/context_support.py`

### Profile-scoped ingestion/indexing

- Ingestion defaults to profile-scoped paths under `data/ingest_profiles/<profile>/...`.
- PostgreSQL schema defaults to ingest profile unless explicitly overridden.
- Eval launchers now enforce ingest-profile/doc-index consistency by default.

Primary modules/scripts:
- `src/andromeda/ingestion/ingest_profile.py`
- `scripts/download.py`, `scripts/process_html_to_markdown.py`, `scripts/chunk.py`, `scripts/build_index.py`
- `scripts/run_full_eval_suite.sh`, `scripts/_env.sh`

## API Surface

Primary endpoints in `src/andromeda/main.py`:

- `GET /health`
- `GET /generation_presets`
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
- `GET /` (main UI)
- `GET /review` (review UI, via review router)

## Repository Map

- API wiring:
  - `src/andromeda/main.py`
- Query runtime:
  - `src/andromeda/query/runtime.py`
  - `src/andromeda/query/streaming.py`
  - `src/andromeda/query/conversation.py`
- Runtime builders/config:
  - `src/andromeda/runtime/builders.py`
- Retrieval:
  - `src/andromeda/retrieval/db.py`
  - `src/andromeda/retrieval/retriever.py`
- Prompting and LLM clients:
  - `src/andromeda/llm/qa.py`
  - `src/andromeda/llm/clients.py`
- Ingestion:
  - `src/andromeda/ingestion/*`
  - `scripts/download.py`, `scripts/process_html_to_markdown.py`, `scripts/chunk.py`, `scripts/build_index.py`
- Evaluation:
  - `src/andromeda/eval/*`
  - `scripts/run_eval.py`, `scripts/score_eval.py`
  - `scripts/run_planner_eval.py`, `scripts/score_planner_eval.py`

## Quickstart

```bash
cp .env.example .env
source .venv/bin/activate
pip install -e ".[dev]"
npm install
```

Required env examples:
- `POSTGRES_DSN` (or `DATABASE_URL`)
- chat/embed model endpoint variables (OpenAI-compatible or provider-specific)

Run app:

```bash
source .venv/bin/activate
python -m uvicorn andromeda.main:app --host 0.0.0.0 --port 8000 --reload
```

UI:
- `http://localhost:8000/`
- `http://localhost:8000/review`

## Common Workflows

Ingestion/indexing (profile-driven):

```bash
source .venv/bin/activate
bash scripts/download.sh
bash scripts/process_html_to_markdown.sh
bash scripts/chunk.sh
bash scripts/build_index.sh
```

Run full eval suite:

```bash
source .venv/bin/activate
bash scripts/run_full_eval_suite.sh
```

Run planner eval suite:

```bash
source .venv/bin/activate
bash scripts/run_planner_eval_suite.sh
```

Detailed eval runbook:
- `README_EVAL.md`
