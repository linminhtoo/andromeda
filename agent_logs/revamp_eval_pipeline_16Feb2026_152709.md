# Revamp Eval Pipeline Plan (16 Feb 2026, 15:27:09)

## Context checkpoints reviewed
- `agent_logs/LOGBOOK.md`
- `CHANGELOG.md`
- `README.md`
- `agent_logs/Evaluating Long-Context Question & Answer Systems.html`

## Scope
Revamp evaluation to explicitly score **helpfulness** (separate from faithfulness), tighten experiment ergonomics, and run an end-to-end iteration cycle:
1. Single-ticker eval iterations first.
2. Multi-ticker eval iterations next.
3. Record each experiment clearly with reproducible commands and observed deltas.

## Technical approach
- Add a new LLM judge rubric `helpfulness_v1` based on relevance + comprehensiveness + conciseness.
- Update scoring to run multiple judges per query kind and expose judge-level metrics in summaries and review artifacts.
- Improve score artifacts for analysis (explicit helpfulness columns + judge map output) so review is easier and interview-ready.
- Run pipeline end-to-end on the active ingest profile (download/process/chunk/build index if needed), generate eval sets, run eval + scoring, inspect failures, then tune prompts/logic.
- Tune runtime behavior in two stages:
  - Single-ticker quality improvements first (response grounding/helpfulness balance).
  - Multi-ticker quality improvements after single-ticker metrics are stable.

## Phases

### Phase 1: Eval criteria + artifact upgrades
Acceptance criteria:
- `helpfulness_v1` judge exists and is callable through existing judge plumbing.
- `score_eval` outputs include explicit helpfulness signal per case.
- Summary contains judge-level fail rates (including helpfulness) by kind.
- Existing tests updated/extended and passing.

### Phase 2: Single-ticker baseline + targeted improvement
Acceptance criteria:
- Single-ticker eval set generated and scored with helpfulness.
- At least one concrete prompt/logic change applied based on observed failure patterns.
- Re-run shows measurable quality improvement on targeted single-ticker metrics.
- Experiment notes include commands, run dirs, key metrics, and qualitative examples.

### Phase 3: Multi-ticker baseline + targeted improvement
Acceptance criteria:
- Multi-ticker eval set generated and scored (including helpfulness).
- At least one concrete multi-ticker prompt/logic improvement implemented.
- Re-run shows measurable quality gains on comparison/multi-ticker criteria.
- Experiment notes include before/after evidence.

### Phase 4: Validation + documentation
Acceptance criteria:
- `pre-commit run --all` passes.
- `pytest -vvv tests/` passes.
- `CHANGELOG.md` updated for behavior changes.
- `agent_logs/LOGBOOK.md` appended with implementation lineage + experiments.
- Experiment scripts preserved under `agent_logs/` (except pre-commit/pytest scripts, per repo rules).

## files_to_change
- `src/finrag/eval/judges.py`
- `src/finrag/eval/scoring.py`
- `src/finrag/eval/schema.py` (only if needed for cleaner structured score outputs)
- `scripts/score_eval.py`
- `scripts/align_judge.py`
- `tests/test_eval_schema_scoring.py`
- `tests/test_eval_metrics.py` (if new helper metrics are introduced)
- `src/finrag/qa.py` (prompt improvements after baseline analysis)
- `src/finrag/query_runtime.py` (logic improvements after baseline analysis)
- `scripts/download.py` (optional ticker scope ergonomics)
- `CHANGELOG.md`
- `agent_logs/LOGBOOK.md`

## new_files
- `agent_logs/revamp_eval_pipeline_16Feb2026_152709.md` (this plan)
- `agent_logs/*_eval_experiment_*.md` (run-by-run experiment logs)
- `agent_logs/*_run_*.sh` (saved experiment scripts, excluding pure pre-commit/pytest wrappers)

## Potential add-ons (not in current scope)
- Pairwise helpfulness comparison evaluator (A/B answer judging).
- Auto-generated failure slices by question template/topic.
- Lightweight dashboard for metric trends across eval runs.
