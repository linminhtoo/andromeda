# Revamp Eval Pipeline - Faithfulness-Focused Iteration (16 Feb 2026, 23:05)

## Scope
Improve single-ticker faithfulness in a generalizable way (no `--enable-refine` dependency), then validate on multi-ticker while keeping settings aligned with deployed app defaults.

## Technical approach
1. Prompt-template tightening for narrative questions
- Strengthen narrative guidance to require direct quote support for numerical statements and to prohibit extrapolation/annualization unless explicitly stated.
- Keep changes generic and question-type driven, not ticker-specific.

2. Lightweight methodological guardrail
- Add deterministic post-generation filtering for narrative answers:
  - detect numeric claims with citations
  - verify numeric tokens against cited chunk text/context
  - replace unsupported numeric claim lines with explicit "Not explicitly stated" fallback
- Keep runtime cost minimal (string processing only; no extra LLM roundtrip).

3. Eval-harness correctness improvement
- Update judge context construction to prioritize chunks explicitly cited in the answer before filling with remaining top chunks.
- This reduces false faithfulness fails caused by truncation omitting cited evidence.

4. Data-driven evaluation loop
- Run single-ticker eval first (`thread` backend, `concurrency=8`, normal preset, full chunks, tools enabled, higher timeout).
- Analyze failure deltas and only then run multi-ticker comparison eval.
- Refresh dashboard artifacts and compare key runs.

## Phases and acceptance criteria

### Phase 1 - Code changes + tests
Acceptance criteria:
- New prompt and filtering logic implemented and covered by unit tests.
- Judge-context cited-chunk prioritization implemented and covered by tests.
- Focused test suite passes.

### Phase 2 - Single-ticker experiment
Acceptance criteria:
- One new single-ticker run completes end-to-end with scoring.
- Faithfulness/hallucination failure analysis documented with concrete metrics and examples.

### Phase 3 - Multi-ticker experiment + reporting
Acceptance criteria:
- One new multi-ticker run completes end-to-end with scoring.
- Dashboard regenerated with new runs.
- `LOGBOOK.md` and `CHANGELOG.md` updated with experiments, outcomes, and rationale.

## Files to change
- `src/andromeda/qa.py`
- `src/andromeda/query_runtime.py`
- `src/andromeda/eval/scoring.py`
- `tests/test_query_runtime_tools_first.py`
- `tests/test_eval_schema_scoring.py`
- `agent_logs/LOGBOOK.md`
- `CHANGELOG.md`

## New files
- `agent_logs/20260216_23xxxx_eval_single_holistic_normal_v14_...sh`
- `agent_logs/20260216_23xxxx_eval_multi_holistic_normal_v2_...sh`
- (optional) short analysis helper script in `agent_logs/` if needed

## Potential add-ons (not in current scope)
- Claim-level verifier model pass (RefChecker-style) for deeper faithfulness diagnostics.
- Pairwise helpfulness eval mode for model-vs-model comparison across runs.
