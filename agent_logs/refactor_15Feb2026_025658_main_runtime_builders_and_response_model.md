# main.py Runtime Builder Extraction + `response_model` Adoption Plan (15Feb2026 02:56:58)

## Goal
Keep `src/finrag/main.py` focused on API wiring by moving env/config/service-builder logic into a dedicated module, and update structured LLM planning calls to use `response_model`.

## Technical approach
1. Create `src/finrag/runtime_builders.py` with:
- env parsing/coercion helpers
- LLM client builders
- retrieval/reranker builders
- ticker ingestion runtime config builder
2. Update `src/finrag/main.py` to import and use the new builder functions, removing duplicated inline logic.
3. Update `src/finrag/query_runtime.py` planner call to pass `response_model=PlannerDecision`, then validate output robustly.
4. Run full validation and document behavior updates.

## Phases

### Phase 1: Extract runtime builder module
Acceptance criteria:
- `main.py` no longer contains the env/coercion/builder implementation bodies.
- Existing runtime behavior remains unchanged.

### Phase 2: Structured planner output
Acceptance criteria:
- Planner call uses `llm.chat(..., response_model=PlannerDecision)`.
- Fallback parsing remains safe when provider output is imperfect.

### Phase 3: Validate + document
Acceptance criteria:
- `pre-commit run --all` passes.
- `pytest -vvv tests/` passes.
- `CHANGELOG.md` and `agent_logs/LOGBOOK.md` updated.

## files_to_change
- `src/finrag/main.py`
- `src/finrag/query_runtime.py`
- `CHANGELOG.md`
- `agent_logs/LOGBOOK.md`

## new_files
- `src/finrag/runtime_builders.py`
- `agent_logs/refactor_15Feb2026_025658_main_runtime_builders_and_response_model.md`

## Future work (suggestion only)
- Consider generic typing overloads for `LLMClient.chat(...)` so `response_model` can return parsed models directly.
