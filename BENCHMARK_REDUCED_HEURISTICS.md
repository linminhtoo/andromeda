# Benchmark: Reduced-Heuristics Branch

_Last updated: 2026-02-18_

## 1) Scope
This report covers Task 2 for branch `mlin/reduce-hardcoded-heuristics`:
- re-run the eval pipeline with current deploy-matched settings,
- analyze failures,
- perform a manual judge audit (Codex reasoning, no judge-LLM self-audit),
- compare against previously recorded benchmark baselines in `BENCHMARK.md`.

## 2) Run Configuration
Core settings used:
- mode: `normal`
- tools: enabled
- refine: disabled
- generation workers: `12` (thread backend)
- query timeout/retries: `350s`, `1`
- judge workers: `12`
- judge context: `80000`
- judge timeout/retries: `350s`, `1`
- schema: `eval_revamp_combined_512_20260217`

Run group manifest:
- `eval/results_revamp/full_suite/reduced_heuristics_full_retry4_envoverride_20260218_195034.manifest.json`

Run dirs:
- `eval/results_revamp/full_suite/eval_run.reduced_heuristics_full_retry4_envoverride_20260218_195034.single100.normal.tools12.norefine.20260218_195034`
- `eval/results_revamp/full_suite/eval_run.reduced_heuristics_full_retry4_envoverride_20260218_195034.multi60.normal.tools12.norefine.20260218_200838`
- `eval/results_revamp/full_suite/eval_run.reduced_heuristics_full_retry4_envoverride_20260218_195034.open200.normal.tools12.norefine.20260218_202301`

## 3) Topline Metrics (This Run)

### 3.1 Generation throughput/latency
| suite | n | n_err | avg_total_ms | wall_total_ms | qps |
|---|---:|---:|---:|---:|---:|
| single100 | 100 | 1 | 59,540.45 | 846,854.45 | 0.1181 |
| multi60 | 60 | 0 | 134,343.77 | 708,687.42 | 0.0847 |
| open200 | 200 | 0 | 63,161.56 | 1,074,835.48 | 0.1861 |

### 3.2 Judge-facing fail rates
- single100 (`score_summary.json`):
  - factual fail: `0.0882`
  - open faithfulness fail: `0.1333`
  - refusal fail: `0.0000`
  - distractor focus fail: `0.0667`
- multi60:
  - comparison fail: `0.1167`
- open200:
  - open faithfulness fail: `0.1350`
  - open helpfulness fail: `0.0050`

## 4) Comparison vs Previous Baseline (`BENCHMARK.md`)
Reference row in `BENCHMARK.md`:
- `baseline_normal`: factual fail `0.0857`, open faith fail `0.1667`, comparison fail `0.0167`.

Comparison (closest axes):
- factual fail: `0.0882` (near parity; slightly worse by +0.0025)
- open faithfulness fail: `0.1333` (improved by -0.0334)
- comparison fail: `0.1167` (material regression, +0.1000)

Interpretation:
- removing brittle heuristics did **not** materially hurt factual fail rate,
- faithfulness on open-ended remained improved versus historical baseline,
- comparison handling regressed strongly and is now the dominant quality gap on multi-ticker prompts.

## 5) Timeout Incident Log (Generation)
Observed and captured in `agent_logs/LOGBOOK.md`:
- hard failure query:
  - `query_id=1dd6251b-e62b-4e58-ae52-35a1253e14c3`
  - question: "What was LITE's net income in its 10-Q filed 2026-02-04?"
  - failure: timed out after 2 attempts (`350s` + retry), `n_err=1`
  - scavenged output: no draft/final answer, no tool trace, generation error record persisted.
- recovered long-tail examples:
  - `aada22de-6020-41aa-be15-5516f64b0aca` (MSFT total revenue) succeeded on retry.
  - `598beb04-ec0c-4314-893e-2deb8f167179` (INTC vs NVDA comparison) succeeded on retry.

### 5.1 Isolated replay of the LITE timeout query
To check whether this was purely batch-queue starvation, I ran the same query in isolation.

- Query: `What was LITE's net income in its 10-Q filed 2026-02-04?`
- Probe A (`agent_logs/scripts/eval/20260218_220200_probe_lite_isolated_latency.sh`):
  - direct single-call runtime probe with outer `timeout 500s`
  - outcome: process timed out (`exit 124`) before returning
- Probe B (`agent_logs/scripts/eval/20260218_221400_probe_lite_single_eval_timeout350.sh`):
  - single-query `run_eval` with `concurrency=1`, `query_timeout_s=350`, `query_max_retries=0`
  - run dir: `agent_logs/reports/retrieval_eval_20260218/lite_single_eval_probe/eval_run.lite_isolated_timeout350.20260218_220015`
  - outcome: success in `20601 ms` (`n_ok=1`, `n_err=0`), with tool trace and retrieved/reranked chunks present.

Inference:
- The long-tail timeout is not only a batching artifact; isolated calls can still hit pathological slow behavior.
- However, the same query can also complete quickly in isolated eval mode, which is consistent with intermittent decode/runtime stalls rather than deterministic query complexity.

## 6) Manual Judge Audit (Codex, Non-Circular)

### 6.1 Method
To avoid circularity, the audit did **not** call the judge LLM.
- Built decision table:
  - `eval/results_revamp/full_suite/reduced_heuristics_full_retry4_envoverride_20260218_195034.judge_audit_manual/decision_audit.raw.csv`
- Full 698-row decision set was split into six shards and manually labeled by Codex workers using rubric-by-`judge_id` reasoning.
- Merged labeled output:
  - `eval/results_revamp/full_suite/reduced_heuristics_full_retry4_envoverride_20260218_195034.judge_audit_manual/decision_audit.codex_manual.csv`
- Reliability report:
  - `eval/results_revamp/full_suite/reduced_heuristics_full_retry4_envoverride_20260218_195034.judge_audit_manual/judge_reliability_report.codex_manual.json`

### 6.2 Alignment summary (test split)
| judge | n_test | accuracy | precision_fail | recall_fail | Cohen's kappa (test) | notes |
|---|---:|---:|---:|---:|---:|---|
| faithfulness_v1 | 58 | 0.9828 | 0.8750 | 1.0000 | 0.9235 | strong alignment |
| factual_correctness_v1 | 9 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | tiny sample |
| helpfulness_v1 | 85 | 0.9882 | 1.0000 | 0.5000 | 0.6614 | under-calls fail cases |
| comparison_v1 | 15 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | aligned on this set |
| focus_v1 | 4 | 1.0000 | 0.0000 | 0.0000 | 1.0000 | no fail cases in test split |
| refusal_v1 | 5 | 0.8000 | 0.0000 | 0.0000 | 0.0000 | misses refusal-needed cases |

### 6.3 Cohen's kappa on manually audited dev/test splits
Computed from `judge_reliability_report.codex_manual.json` using manual labels (`human_label`) vs judge decision (`judge_prediction`) per `judge_id`.

| judge | kappa_dev | kappa_test |
|---|---:|---:|
| comparison_v1 | 1.0000 | 1.0000 |
| factual_correctness_v1 | 0.6479 | 1.0000 |
| faithfulness_v1 | 0.9233 | 0.9235 |
| focus_v1 | 1.0000 | 1.0000 |
| helpfulness_v1 | 0.2809 | 0.6614 |
| refusal_v1 | 0.0000 | 0.0000 |

Aggregate agreement across all audited decisions:
- pooled kappa (dev): `0.8294` (`n=522`)
- pooled kappa (test): `0.8708` (`n=176`)
- macro-average kappa (dev/test): `0.6420` / `0.7641`
- sample-weighted kappa (dev/test): `0.5792` / `0.7828`

Interpretation:
- Overall agreement is strong at pooled level.
- The weakest agreement remains in `helpfulness_v1` and `refusal_v1`, consistent with observed under-calling of fail cases.

### 6.4 Key disagreement patterns
Confusion from full 698 labeled decisions:
- false positives: `4` total
  - mostly faithfulness over-flags (`3`) and one factual false positive.
- false negatives: `10` total
  - helpfulness under-flags (`6`) for non-responsive comparison/analysis answers,
  - refusal under-flags (`3`) where out-of-scope prompts were met with clarification instead of refusal,
  - faithfulness under-flag (`1`) on unsupported filing-availability claim.

## 7) Genuine Pipeline Failures (from manual audit)
Main categories of true failures (`human_label=1`):
- comparison completeness failures (`comparison_v1`, `7`): model defers/clarifies instead of producing requested side-by-side analysis.
- open-ended faithfulness failures (`faithfulness_v1`, `29`): period mismatch and unsupported specific claims remain the largest category.
- refusal behavior gaps (`refusal_v1`, `3`): out-of-scope ticker prompts not refused strongly enough.
- helpfulness failures (`helpfulness_v1`, `8`): mostly non-answers/deferrals for requested comparative analysis.

## 8) Surprising Findings and Hypotheses
1. Removing brittle heuristics improved maintainability without collapsing factual/open-ended quality.
2. Multi-ticker comparison degraded sharply; likely because previous heuristic scaffolding implicitly forced comparative structure.
3. Faithfulness judge quality is now relatively strong under Codex-manual audit; biggest remaining reliability issue is helpfulness/refusal under-calling.
4. Timeout outliers still materially affect wall-clock and can dominate throughput for small suites.

## 9) Immediate Follow-ups
1. Improve comparison answer planning (explicit required-output structure for multi-ticker comparison prompts).
2. Tighten refusal policy for out-of-scope tickers (prefer explicit refusal over vague clarifying loops).
3. Add retry+continue safeguards for long-tail timed-out generations (already partially in place).
4. Keep judge audits separated from judge-model outputs (Codex-manual process retained as the non-circular check).
