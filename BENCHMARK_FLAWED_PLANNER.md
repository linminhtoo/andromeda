# Flawed Planner Prompt Regression (20 Feb)

## Why this write-up exists
I stopped the active run on request because the planner prompt appears too loose, causing excessive `clarification_required` decisions and downstream refusal behavior.

## Run status at stop time
- Completed:
  - `eval/results_revamp/full_suite_ablation/eval_run.full_suite_ablation_20260220_001447.baseline_best.single100.normal.tools12.norefine.20260220_001448`
  - `eval/results_revamp/full_suite_ablation/eval_run.full_suite_ablation_20260220_001447.baseline_best.multi60.normal.tools12.norefine.20260220_002746`
  - `eval/results_revamp/full_suite_ablation/eval_run.full_suite_ablation_20260220_001447.baseline_best.open200.normal.tools12.norefine.20260220_003443`
  - `eval/results_revamp/full_suite_ablation/eval_run.full_suite_ablation_20260220_001447.ablation_no_rerank.single100.normal.tools12.norefine.20260220_010156`
  - `eval/results_revamp/full_suite_ablation/eval_run.full_suite_ablation_20260220_001447.ablation_no_rerank.multi60.normal.tools12.norefine.20260220_011025`
  - `eval/results_revamp/full_suite_ablation/eval_run.full_suite_ablation_20260220_001447.ablation_no_rerank.open200.normal.tools12.norefine.20260220_011749`
  - `eval/results_revamp/full_suite_ablation/eval_run.full_suite_ablation_20260220_001447.ablation_no_material_cap.single100.normal.tools12.norefine.20260220_013728`
  - `eval/results_revamp/full_suite_ablation/eval_run.full_suite_ablation_20260220_001447.ablation_no_material_cap.multi60.normal.tools12.norefine.20260220_014954`
- Interrupted mid-run:
  - `eval/results_revamp/full_suite_ablation/eval_run.full_suite_ablation_20260220_001447.ablation_no_material_cap.open200.normal.tools12.norefine.20260220_020229`
  - Partial artifact only (`generations.jsonl` with 5 rows), no scored summary.

## Key regression signal
- Current baseline `open200`:
  - `faithfulness_v1` fail: `0.2764`
  - `helpfulness_v1` fail: `0.4372`
- Previous reduced-heuristics reference (`2026-02-18`):
  - `eval/results_revamp/full_suite/eval_run.reduced_heuristics_full_retry4_envoverride_20260218_195034.open200.normal.tools12.norefine.20260218_202301`
  - `faithfulness_v1` fail: `0.1350`
  - `helpfulness_v1` fail: `0.0050`

## Root-cause diagnosis
The biggest change is planner behavior, not reranker toggles:

- Previous run planner actions (`open200`, n=200):
  - `answer`: `199`
  - `clarification_required`: `1`
- Current baseline planner actions (`open200`, n=199 ok rows):
  - `answer`: `167`
  - `clarification_required`: `32`

Every one of these `32` clarification cases triggered `refuse_unindexed_ticker_candidates` using bogus inferred symbols.

Examples from traces:
- ATI thesis query -> inferred candidates: `GC=F, ALI=F, RB=F, HO=F, PL=F`
- GEV capital allocation query -> inferred candidates: `CAPEX, EDD`
- IESC risk query -> inferred candidate: `TDOG`

This creates false refusals even when the true ticker is indexed.

## Quantified impact of this failure mode (current baseline open200)
- `clarification_required + refuse_unindexed` cases: `32`
- Helpfulness fails among those: `32/32`
- Faithfulness fails among those: `28/32`
- Share of all helpfulness fails explained by this single mode: `32/87` (~36.8%)

## Additional ablation note
- Turning off reranker improved open-ended faithfulness (`0.2764 -> 0.1950`) but did not fix helpfulness (`0.4372 -> 0.4300`), which is consistent with the planner/refusal issue dominating helpfulness failures.
- Removing material-point cap severely worsened latency/tail behavior and did not provide clear quality upside in completed slices.

## Immediate fix direction
1. Planner prompt: tighten `clarification_required` criteria to avoid triggering when a valid indexed ticker is present and intent is answerable.
2. Runtime guardrail: do not call `refuse_unindexed_ticker_candidates` when planner returns valid structured output with empty tickers and `clarification_required`.
3. Ticker inference fallback: never treat generic finance tokens (`CAPEX`, `M&A`, etc.) as ticker candidates for refusal logic.
4. Add regression tests with the exact failing queries above.
