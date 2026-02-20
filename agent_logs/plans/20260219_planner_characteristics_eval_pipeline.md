# 20260219 Planner Characteristics Eval Pipeline Plan

## Objective
Add a dedicated evaluation pipeline to measure whether the planner correctly recognizes query characteristics, using a manually authored (non-LLM-generated) 100-query ground-truth dataset.

## Scope
1. Define planner-eval schema and scoring utilities.
2. Create a manually curated 100-query planner eval dataset with characteristic labels.
3. Add run + score scripts modeled after existing eval flow.
4. Add tests for dataset integrity and scoring logic.
5. Update docs/changelog/logbook.

## Technical Approach

### Phase 1: Schema + scoring core
- Add planner eval models (query/prediction).
- Add multi-label classification scoring (exact match, micro/macro precision/recall/F1, per-characteristic confusion).
- Add optional action-accuracy scoring for rows with expected action labels.

Acceptance criteria:
- Scoring functions produce deterministic summary from synthetic fixtures.
- Unit tests cover core metric calculations.

### Phase 2: Manual 100-query ground-truth dataset
- Build a manually curated query bank covering all planner characteristics and combinations:
  - comparison
  - market_data
  - financial_metrics
  - filing_narrative
  - period_scoped
  - simple_numeric
- Include a small subset with expected action labels (answered/refused/clarification_required).
- Ensure query diversity across companies, intents, and formulations.

Acceptance criteria:
- Dataset count is exactly 100.
- All labels validate against schema.
- No LLM-assisted generation used.

### Phase 3: Run + score scripts
- Add `run_planner_eval.py`:
  - load planner eval queries
  - call runtime `plan_query(...)`
  - save predictions + timing/errors + run summary
  - include timeout/retry support
- Add `score_planner_eval.py`:
  - compare predictions vs ground truth
  - write summary JSON, per-query score JSONL, review CSV, markdown summary

Acceptance criteria:
- Scripts parse `--help` and run in dry/offline test contexts.
- Outputs follow reproducible run-dir structure similar to existing eval pipeline.

### Phase 4: Validation + docs
- Add tests for dataset and scorer.
- Run `pytest tests/` and `PRE_COMMIT_HOME=/tmp/pre-commit-cache pre-commit run --all`.
- Update `CHANGELOG.md` and append logbook entry.

Acceptance criteria:
- Test suite passes.
- Pre-commit passes.
- Changelog + logbook document what changed and why.

## files_to_change
- `src/andromeda/eval/` (new planner eval modules)
- `scripts/` (new planner eval scripts)
- `tests/` (new planner eval tests)
- `CHANGELOG.md`
- `agent_logs/LOGBOOK.md`

## new_files
- `src/andromeda/eval/planner_schema.py`
- `src/andromeda/eval/planner_dataset.py`
- `src/andromeda/eval/planner_scoring.py`
- `scripts/make_planner_eval_set.py`
- `scripts/run_planner_eval.py`
- `scripts/score_planner_eval.py`
- `eval/eval_queries_planner_characteristics_manual100_20260219.jsonl`
- `tests/test_planner_eval_dataset.py`
- `tests/test_planner_eval_scoring.py`

## Future add-ons (not in current scope)
- Add bootstrap confidence intervals for planner metrics.
- Add category-aware slices by query archetype and ticker sector.
- Add planner calibration set with human disagreement annotations.
