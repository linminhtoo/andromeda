# Plan: Unify finance tool planner flag and gate LLM tool-context inclusion

## Phase 1: Runtime planner flag refactor
Acceptance criteria:
- Replace split planner booleans (`use_yfinance`, `use_edgar_financials`) with unified `use_finance_tools`.
- Runtime planning resolves `(use_rag, use_finance_tools)` coherently and blocks invalid `(false, false)` path.
- Planner prompt/few-shot/repair schemas are updated to use only `use_finance_tools`.

files_to_change:
- `src/andromeda/query/runtime.py`

new_files:
- none

## Phase 2: Always-run tools for UI + context gating
Acceptance criteria:
- Finance tools execute for planned tickers regardless of `use_finance_tools` (unless globally disabled).
- Full tool outputs remain in API response for UI.
- LLM prompt context includes tool outputs only when `use_finance_tools=true`.
- Streaming path uses same context-gating behavior as non-streaming path.

files_to_change:
- `src/andromeda/query/runtime.py`
- `src/andromeda/query/streaming.py`

new_files:
- none

## Phase 3: Compact price-history context representation
Acceptance criteria:
- Preserve full OHLC payload for frontend chart rendering.
- `tool_context_text(...)` compresses price-history payload to compact 12-month monthly closes (2 decimals) for LLM context.

files_to_change:
- `src/andromeda/finance_tools.py`
- `tests/test_finance_tools.py`

new_files:
- none

## Phase 4: Eval/test plumbing updates
Acceptance criteria:
- Planner-eval schema/scripts/tests migrate to `use_finance_tools`.
- Runtime tests updated for new planner field and behavior.
- `pytest tests/` and `pre-commit` pass.

files_to_change:
- `src/andromeda/eval/planner_schema.py`
- `scripts/run_planner_eval.py`
- `tests/test_planner_eval_pipeline.py`
- `tests/test_query_runtime_tools_first.py`
- `CHANGELOG.md`
- `agent_logs/LOGBOOK.md`

new_files:
- none
