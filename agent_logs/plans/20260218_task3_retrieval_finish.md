# 20260218 Task3 Retrieval Finish Plan

## Goal
Complete Task 3 from the reduced-heuristics branch work: finalize retrieval/rerank evaluation with Codex-manual audit outputs and publish a readable benchmark report.

## Technical Approach
1. Collect and verify existing artifacts from the completed full-suite run and manual 300-sample retrieval audit.
2. Compute additional summary metrics needed for interpretation:
   - label coverage and relevance prevalence
   - pre/post membership and rank shifts for relevant chunks
   - precision-style summaries from manually audited rows
   - weak-label calibration interpretation with bootstrap CI
3. Write `BENCHMARK_RETRIEVAL.md` with:
   - exact experiments and artifact paths
   - metrics tables
   - key findings and hypotheses
   - concrete follow-up actions
4. Append a detailed `agent_logs/LOGBOOK.md` entry with scripts, artifact paths, and conclusions.

## Phases + Acceptance Criteria

### Phase 1: Artifact Verification
Acceptance criteria:
- All required artifacts exist and are readable.
- Missing pieces are identified and backfilled if needed.

### Phase 2: Retrieval Analysis
Acceptance criteria:
- Analysis outputs (JSON/CSV) include at least:
  - manual-label prevalence
  - pre/post relevant rank statistics
  - calibration metrics with CI
- Outputs are written under `agent_logs/reports/`.

### Phase 3: Reporting
Acceptance criteria:
- `BENCHMARK_RETRIEVAL.md` is created with reproducible commands and results tables.
- `agent_logs/LOGBOOK.md` has a new entry with a concise but complete lineage.

## files_to_change
- `BENCHMARK_RETRIEVAL.md`
- `agent_logs/LOGBOOK.md`
- `agent_logs/scripts/eval/20260218_*.sh`

## new_files
- `agent_logs/plans/20260218_task3_retrieval_finish.md`
- `agent_logs/reports/retrieval_eval_20260218/*.json`
- `agent_logs/reports/retrieval_eval_20260218/*.md`
