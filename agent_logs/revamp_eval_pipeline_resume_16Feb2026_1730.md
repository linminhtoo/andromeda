# Eval Revamp Resume Plan - 16 Feb 2026 (1730)

## Objective
Resume eval iteration with healthy vLLM, prioritize reducing open-ended faithfulness failures, and enforce tools-first behavior for simple numeric questions with RAG fallback only when tool outputs are insufficient.

## Phases

### Phase 1 - Runtime logic hardening (single-service changes)
Acceptance criteria:
- If planner sets `use_rag=false` but finance tools return no actionable data, pipeline falls back to RAG retrieval automatically.
- Existing tools-only behavior remains unchanged when tool outputs are usable.

Files to change:
- `src/finrag/query_runtime.py`
- `tests/test_query_runtime_tools_first.py`

### Phase 2 - Validation gates
Acceptance criteria:
- `pre-commit run --all` passes.
- `pytest -vvv tests/` passes.

Files to change:
- none (execution only)

### Phase 3 - Single-ticker experiments (priority)
Acceptance criteria:
- Complete at least one clean single-ticker post-change run with valid scoring.
- Compare against prior single baseline (`single_balanced_validated_baseline_v2`) focusing on:
  - `open_ended_judge_fail_rate` (faithfulness)
  - factual numeric metrics
- Run a tools-enabled single run to verify factual numeric behavior under tools-first path.

Artifacts:
- new scripts under `agent_logs/`
- new run dirs under `eval/results_revamp/single/`

### Phase 4 - Documentation and handoff
Acceptance criteria:
- Append concise experiment log + outcomes in `agent_logs/LOGBOOK.md`.
- Update `CHANGELOG.md` for behavior changes.

## Suggested future work (not in current scope)
- Add metric-level tool extraction in scoring (explicitly detect whether final numeric answer came from tool payload vs RAG evidence).
- Add dedicated `simple_numeric` eval subset for stress-testing tools-first policy.
