# Tools-First Answering Overhaul Plan (15Feb2026 02:03:26)

## Goal
Move query handling from a fixed retrieve->rerank->generate path to a tools-first orchestration that can:
- plan retrieval filters before retrieval,
- validate requested tickers against indexed DB coverage,
- ask clarifying questions and continue in multi-turn mode,
- execute per-ticker retrieval for multi-entity questions,
- preserve both `/query` and `/query_stream` behavior for answered cases.

## Technical approach
1. Add DB/retriever tool primitives for ticker catalog lookup.
2. Add a planner/orchestrator inside `RAGService` that executes explicit tool steps and records a tool trace.
3. Introduce conversation state for clarification turns (`conversation_id`) with pending clarification context.
4. Rewire sync + streaming endpoints to use the shared planner and execution helpers.
5. Update frontend to persist `conversation_id` and correctly handle non-answer outcomes (clarification/refusal).
6. Add tests for planner outcomes, multi-turn flow, and compatibility of existing happy paths.

## Phases

### Phase 1: Retrieval tool primitives + planning models
Acceptance criteria:
- `PostgresDB` can return distinct indexed tickers/company names.
- `PostgresHybridRetriever` exposes this as a direct method.
- New typed planner/tool-trace models exist in `main.py`.

### Phase 2: Tools-first orchestrator in backend
Acceptance criteria:
- `RAGService` runs a plan stage before retrieval.
- Plan stage can produce one of: answer, clarification_required, refused.
- Requested or inferred tickers not in indexed DB produce immediate refusal.
- Multi-ticker plans run retrieval/rerank per ticker, then merge/dedupe before generation.
- Sync endpoint `/query` returns `conversation_id`, `status`, and optional `clarifying_question`.

### Phase 3: Streaming + frontend multi-turn support
Acceptance criteria:
- `/query_stream` reuses the same plan stage and handles clarification/refusal without retrieval.
- Streaming response `done.response` includes planner status + `conversation_id`.
- Frontend sends `conversation_id` for follow-up turns.
- Frontend handles clarification-required responses without breaking citation/chunk flows.
- New chat reset clears active conversation context.

### Phase 4: Tests and docs/logs
Acceptance criteria:
- Backend tests cover planner status branches and conversation-id behavior.
- Existing query endpoint behavior test remains passing.
- `CHANGELOG.md` documents user-visible behavior changes.
- `agent_logs/LOGBOOK.md` is appended with scope, observations, and validation outcomes.

## files_to_change
- `src/andromeda/db.py`
- `src/andromeda/retriever.py`
- `src/andromeda/main.py`
- `src/andromeda/static/ts/index/main.ts`
- `tests/test_main_api_e2e.py`
- `CHANGELOG.md`
- `agent_logs/LOGBOOK.md`

## new_files
- `agent_logs/refactor_15Feb2026_020326_tools_first_answering_overhaul.md`
- `agent_logs/20260215_validate_tools_first_answering_overhaul.sh`

## Out of scope for this implementation
- Full OpenAI native tool-calling migration inside `llm_clients` (current deployed vLLM config rejects auto tool calls).
- Persistent conversation storage in PostgreSQL (this pass uses in-process runtime state).
- Advanced NLU for ticker inference beyond pragmatic planner + deterministic normalization.

## Future add-ons (not in current scope)
- Move conversation state to durable storage for multi-worker deployments.
- Add planner confidence scoring and retrieval score-based auto-refusal thresholds.
- Add date-intent inference tools (e.g., “latest filing” -> date filter) with explicit explainability.
