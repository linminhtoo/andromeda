# Plan: Tools-First Finance Integration (yfinance + edgartools + RAG as Function)

## Objective
Integrate yfinance and edgartools as first-class tool sources in the query runtime, keep them complementary to retrieval, and enable planner-driven skipping of RAG when direct tools can answer.

## Phase 1: Add typed finance tool adapters
### Technical approach
- Add a local adapter module that wraps:
  - yfinance market data calls (profile/info, recent news, history samples)
  - edgartools financial statements/metrics via `Company(...).get_financials()` and `get_quarterly_financials()`
- Return JSON-serializable typed payloads for prompt assembly and UI metadata.
- Keep adapters side-effect free and bounded (limited rows/news items).

### Acceptance criteria
- Adapter APIs are importable and typed.
- Adapter methods return stable dict/list payloads and graceful error messages.
- Unit tests cover success + no-data/error fallback behavior with monkeypatching.

### files_to_change
- `src/finrag/query_runtime.py`
- `CHANGELOG.md`
- `agent_logs/LOGBOOK.md`

### new_files
- `src/finrag/finance_tools.py`
- `tests/test_finance_tools.py`

## Phase 2: Extend planner semantics for tool mix and RAG function usage
### Technical approach
- Extend planner decision schema to include tool directives:
  - whether to call yfinance
  - whether to call edgartools financials
  - whether RAG function is required
- Update planner prompt with explicit policy:
  - use RAG for filing-grounded qualitative questions
  - allow tools-only path for direct metric/price/news tasks
  - allow combined path when synthesis needs both.

### Acceptance criteria
- Planner output includes deterministic defaults for new fields.
- Tool trace shows planner directives used for execution.
- Existing clarification/refusal behavior remains intact.

### files_to_change
- `src/finrag/query_runtime.py`
- `tests/test_query_runtime_tools_first.py`

### new_files
- `tests/test_query_runtime_tools_first.py`

## Phase 3: Execute tool calls before/alongside RAG and synthesize final answer
### Technical approach
- Introduce pipeline fields for tool results.
- Execute selected tools after planning and before answer generation.
- Treat RAG as callable function in runtime:
  - if planner says no RAG, skip retrieve/rerank stages.
  - if planner says RAG required, run current retrieval flow.
- Update prompt construction so final answer can synthesize:
  - tool results section
  - RAG context section (if present).
- Maintain streaming compatibility by reusing the same execution object and adding tool-status/tool-result stream events.

### Acceptance criteria
- `/query` and `/query_stream` both support:
  - tools-only
  - rag-only
  - tools + rag
- Response remains backward-compatible shape with enriched `tool_trace` and answers referencing combined evidence.
- Streaming emits informative status and does not break cancellation/history.

### files_to_change
- `src/finrag/query_runtime.py`
- `src/finrag/query_streaming.py`
- `src/finrag/main.py`
- `tests/test_main_api_e2e.py`

### new_files
- none (beyond prior phases)

## Phase 4: Validation + documentation/logging
### Technical approach
- Run mandated checks:
  - `source .venv/bin/activate && pre-commit run --all`
  - `source .venv/bin/activate && pytest -vvv tests/`
- Store executed validation script in `agent_logs/`.
- Update `CHANGELOG.md` and append implementation notes/findings in `agent_logs/LOGBOOK.md`.

### Acceptance criteria
- Pre-commit passes.
- Tests pass.
- Changelog and logbook document behavior changes and experiments.

### files_to_change
- `CHANGELOG.md`
- `agent_logs/LOGBOOK.md`

### new_files
- `agent_logs/20260215_*.sh` (validation script)

## Suggestions (future work, not in current scope)
- Add frontend-specific rendering blocks for finance tool artifacts (mini charts/cards) from structured API fields.
- Add budget/latency policy engine that adaptively limits tool calls based on question complexity.
- Add explicit citation tags for tool outputs (e.g., `[tool=yfinance ticker=AAPL]`).
