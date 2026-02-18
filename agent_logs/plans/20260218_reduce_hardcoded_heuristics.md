# Reduce Hardcoded Heuristics (Planner-First) - 2026-02-18

## Scope
Refactor query planning so the LLM planner is the first-resort decision engine, with heuristic logic only as fallback after planner failure + repair failure. Replace brittle ticker inference regex with yfinance search-backed inference. Disable brittle heuristic retrieval post-processing in normal flow.

## Phase 1 - Planner-first structured classification + repair

### Approach
- Extend planner schema to include non-mutually-exclusive `characteristics` labels.
- Upgrade planner prompt with few-shot characteristic mapping examples.
- Add a repair prompt path:
  1) primary planner request,
  2) if invalid JSON/schema -> repair request using original raw output,
  3) if still invalid -> fallback heuristics.
- Ensure runtime tool/routing defaults come from planner structured outputs (not regex functions) when planner succeeds.

### Acceptance criteria
- Valid planner output drives routing without regex-based question classification.
- Invalid planner output triggers exactly one repair attempt.
- Fallback planner heuristics are used only after primary + repair failure.

## Phase 2 - Extract heuristics into dedicated fallback module

### Approach
- Move regex/question-classification fallback logic into `src/andromeda/query/planner_heuristics.py`.
- Keep runtime references to heuristics constrained to fallback-only path.
- Keep heuristics implementation private and explicitly labeled fallback behavior.

### Acceptance criteria
- `runtime.py` no longer contains first-resort regex routing logic.
- Heuristic classification and regex ticker extraction are not used in successful planner paths.

## Phase 3 - Replace brittle ticker inference with yfinance search

### Approach
- Implement fallback ticker inference using `yfinance.Search(...)`.
- Normalize/validate results against indexed ticker catalog.
- Keep deterministic dedupe and bounded results.

### Acceptance criteria
- Fallback ticker inference does not use regex-only extraction as primary source.
- Inference degrades safely when yfinance import/network fails.

## Phase 4 - Disable brittle retrieval heuristics in normal path

### Approach
- Disable adaptive retrieval budget scheduling in active execution path.
- Disable MMR diversification and narrative aspect-coverage post-processing in active rerank path.
- Disable narrative query expansion in active retrieval path.

### Acceptance criteria
- Normal execution path does not apply these heuristic transformations.
- Core tools-first + rerank pipeline remains functional.

## Phase 5 - Tests, docs, and changelog

### Approach
- Update `tests/test_query_runtime_tools_first.py` for planner-first + fallback behavior.
- Add/adjust targeted tests for planner repair and yfinance-search fallback.
- Update `CHANGELOG.md` and append summary in `agent_logs/LOGBOOK.md`.

### Acceptance criteria
- `pre-commit run --all` passes.
- `pytest -vvv tests/` passes.
- Changelog/logbook document behavior changes and fallback policy.

## files_to_change
- `src/andromeda/query/runtime.py`
- `src/andromeda/query/planner_heuristics.py` (new)
- `tests/test_query_runtime_tools_first.py`
- `CHANGELOG.md`
- `agent_logs/LOGBOOK.md`

## new_files
- `src/andromeda/query/planner_heuristics.py`

## Suggested future work (out of current scope)
- Add planner decision quality benchmark set + regression gating.
- Add production telemetry for planner parse/repair/fallback rates per query type.
