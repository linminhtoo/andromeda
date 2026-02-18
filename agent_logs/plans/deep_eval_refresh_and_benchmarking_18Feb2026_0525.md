# Deep Eval Refresh + Benchmarking Plan (18 Feb 2026, 05:25)

## Scope
- Aggressively regroup `src/andromeda` modules into clearer subpackages.
- Move existing top-level `agent_logs/` artifacts into nested folders without renaming filenames.
- Create `FUTURE_WORKS.md` (customer/product-oriented, web-grounded).
- Re-run chunk-size ablation using current-best eval settings (`judge_context_chars=80000`) on expanded eval dataset.
- Build latency/accuracy frontier study across multiple tunable knobs (including answering effort), document prioritized proposals, and execute top candidates.

## Phase 1: Source tree regrouping
- Move additional modules into subpackages:
  - retrieval: `db.py`, `retriever.py`
  - llm: `llm_clients.py`, `streaming.py`, `generation_controls.py`, `qa.py`
  - ingestion: `ingest_profile.py`, `ingested_companies.py`, `ingestion_jobs.py`
  - processing: `chunking.py`, `chunk_postprocess.py`, `context_support.py`, `metadata_models.py`
  - docs/review: `source_access.py`, `review_app.py`, `review_ui.py`
- Update imports across `src/`, `scripts/`, `tests/`.
- Keep `src/andromeda/main.py` as API entrypoint.

Acceptance criteria:
- no stale imports to moved modules.
- tests pass after refactor.

files_to_change:
- `src/andromeda/**`
- `scripts/**` (import updates)
- `tests/**` (import updates)
- `src/andromeda*.egg-info/SOURCES.txt`

new_files:
- package `__init__.py` files for new subpackages.

## Phase 2: agent_logs physical organization
- Move files from top-level `agent_logs/` into:
  - `agent_logs/scripts/` (timestamped scripts)
  - `agent_logs/plans/` (planning docs)
  - `agent_logs/audits/` (audit csv/json/md/txt)
  - `agent_logs/reports/` (metrics summaries, iteration summaries)
  - `agent_logs/references/` (external reading material)
  - `agent_logs/artifacts/` (misc large generated artifacts)
- Preserve filenames exactly.
- Update `agent_logs/README.md` with current move map.

Acceptance criteria:
- top-level `agent_logs/` becomes materially cleaner.
- file basenames unchanged.

files_to_change:
- `agent_logs/README.md`
- filesystem layout under `agent_logs/`

new_files:
- none required beyond moved files

## Phase 3: FUTURE_WORKS product roadmap
- Create `FUTURE_WORKS.md` at repo root.
- Use web search for current, credible references on:
  - eval reliability
  - agent/tool routing
  - observability, guardrails, and reliability operations
- Present as customer-outcome roadmap with measurable success criteria.

Acceptance criteria:
- includes prioritized initiatives, customer pains addressed, and measurable KPIs.
- includes source links.

files_to_change:
- `FUTURE_WORKS.md`

new_files:
- `FUTURE_WORKS.md`

## Phase 4: Benchmark reruns and frontier mapping
- Chunk-size ablation rerun:
  - chunk sizes: `256`, `512`, `1024`, `2048`
  - settings: tools-enabled, normal preset, no refine, `12` generation workers, judge `80000/350s/retry=1`
  - dataset: expanded eval dataset (`single_balanced100` + optional comparison/open runs as noted)
- Latency/accuracy frontier study:
  - include answering effort `low/medium/high`
  - propose and execute additional high-priority knobs
  - aggregate metrics + latency into tables/figures
- Document outcomes and prioritized next steps in `agent_logs/LOGBOOK.md`.

Acceptance criteria:
- reproducible scripts saved in `agent_logs/scripts/eval/`.
- result tables and figures generated under `eval/results_revamp/...`.
- logbook entry includes commands, run IDs, metric deltas, and decisions.

files_to_change:
- `agent_logs/scripts/eval/*` (new scripts)
- `eval/results_revamp/...` (new run artifacts)
- `agent_logs/LOGBOOK.md`
- benchmark summary docs in `agent_logs/reports/`

new_files:
- timestamped benchmark scripts and summary reports
