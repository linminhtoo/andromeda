# Benchmark With Fixed Planner (20 Feb 2026)

## Goal
Re-run the requested 3-way end-to-end benchmark after the planner routing fix:
1. `baseline_best`
2. `ablation_no_rerank`
3. `ablation_no_material_cap`

and report quality + latency behavior under the latest full-suite settings.

## Setup
- Run group: `full_suite_ablation_20260220_022028`
- Driver script: `agent_logs/scripts/20260219_2358_run_full_suite_rerank_material_ablation.sh`
- Generation:
  - `mode=normal`
  - `concurrency=12` (thread backend)
  - `query_timeout_s=350`
  - `query_max_retries=1`
  - deploy-matched retrieval settings (`top_k_retrieve=40`, `top_k_rerank=25` via normal preset)
- Judge:
  - `judge_workers=12`
  - `judge_context_chars=80000`
  - `judge_timeout_s=350`
  - `judge_max_retries=1`
- Query suites:
  - `single100`: `eval/eval_queries_combined512_single_balanced100_validated_tol05_20260217.jsonl`
  - `multi60`: `eval/eval_queries_combined512_multi_comparison60_validated_tol05_20260217.jsonl`
  - `open200`: `eval/eval_queries_openended200_diverse_20260217_v1.jsonl`

## Planner-Fix Impact Check (Before vs After)
Primary reference for "before" (flawed planner prompt/routing era):
- `eval/results_revamp/full_suite_ablation/eval_run.full_suite_ablation_20260220_001447.baseline_best.open200.normal.tools12.norefine.20260220_003443`

Current fixed-planner baseline:
- `eval/results_revamp/full_suite_ablation/eval_run.full_suite_ablation_20260220_022028.baseline_best.open200.normal.tools12.norefine.20260220_024910`

### Open200 (baseline_best) delta
- Faithfulness fail: `0.2764 -> 0.1200` (`-15.64` pp)
- Helpfulness fail: `0.4372 -> 0.2800` (`-15.72` pp)

### Routing-trace evidence for root cause removal
`open200` planner/tool traces:
- Flawed run:
  - planner actions: `answer=167`, `clarification_required=32`
  - `refuse_unindexed_ticker_candidates=32`
- Fixed run:
  - planner actions: `answer=200`
  - `refuse_unindexed_ticker_candidates=0`

Interpretation: the major helpfulness regression was primarily caused by erroneous clarification/refusal routing; the routing fix removed that failure mode.

## Exact Experiments Run
### Baseline (`baseline_best`)
- single100: `eval/results_revamp/full_suite_ablation/eval_run.full_suite_ablation_20260220_022028.baseline_best.single100.normal.tools12.norefine.20260220_022029`
- multi60: `eval/results_revamp/full_suite_ablation/eval_run.full_suite_ablation_20260220_022028.baseline_best.multi60.normal.tools12.norefine.20260220_024054`
- open200: `eval/results_revamp/full_suite_ablation/eval_run.full_suite_ablation_20260220_022028.baseline_best.open200.normal.tools12.norefine.20260220_024910`

### Reranker off (`ablation_no_rerank`)
- single100: `eval/results_revamp/full_suite_ablation/eval_run.full_suite_ablation_20260220_022028.ablation_no_rerank.single100.normal.tools12.norefine.20260220_031323`
- multi60: `eval/results_revamp/full_suite_ablation/eval_run.full_suite_ablation_20260220_022028.ablation_no_rerank.multi60.normal.tools12.norefine.20260220_032256`
- open200: `eval/results_revamp/full_suite_ablation/eval_run.full_suite_ablation_20260220_022028.ablation_no_rerank.open200.normal.tools12.norefine.20260220_033214`

### Material cap off (`ablation_no_material_cap`)
- single100: `eval/results_revamp/full_suite_ablation/eval_run.full_suite_ablation_20260220_022028.ablation_no_material_cap.single100.normal.tools12.norefine.20260220_035608`
- multi60: `eval/results_revamp/full_suite_ablation/eval_run.full_suite_ablation_20260220_022028.ablation_no_material_cap.multi60.normal.tools12.norefine.20260220_041300`
- open200 (partial generation, completed scoring): `eval/results_revamp/full_suite_ablation/eval_run.full_suite_ablation_20260220_022028.ablation_no_material_cap.open200.normal.tools12.norefine.20260220_042421`

## Results
### single100
| Experiment | Gen n_ok / n_err | Avg gen total ms | Factual fail | Factual helpfulness fail | Open faithfulness fail | Open helpfulness fail | Distractor focus fail |
|---|---:|---:|---:|---:|---:|---:|---:|
| baseline_best | 99 / 1 | 47,317 | 0.2857 | 0.2571 | 0.1034 | 0.2759 | 0.4000 |
| ablation_no_rerank | 100 / 0 | 40,139 | 0.2857 | 0.2571 | 0.0333 | 0.2667 | 0.4000 |
| ablation_no_material_cap | 99 / 1 | 57,097 | 0.3143 | 0.2571 | 0.1379 | 0.2759 | 0.3333 |

### multi60
| Experiment | Gen n_ok / n_err | Avg gen total ms | Comparison fail | Comparison helpfulness fail |
|---|---:|---:|---:|---:|
| baseline_best | 60 / 0 | 68,428 | 0.5167 | 0.5000 |
| ablation_no_rerank | 60 / 0 | 75,780 | 0.5000 | 0.5167 |
| ablation_no_material_cap | 60 / 0 | 99,446 | 0.5167 | 0.5167 |

### open200
| Experiment | Gen n_ok / n_err | Avg gen total ms | Open faithfulness fail | Open helpfulness fail | Notes |
|---|---:|---:|---:|---:|---|
| baseline_best | 200 / 0 | 56,696 | 0.1200 | 0.2800 | complete |
| ablation_no_rerank | 200 / 0 | 54,507 | 0.1500 | 0.2850 | complete |
| ablation_no_material_cap | 190 / 10* | 85,927** | 0.1684 | 0.2947 | partial generation; scored on 200 queries with 190 generated answers |

\* `ablation_no_material_cap/open200`: 191 generation rows written, 1 hard timeout error row, 9 query IDs missing due stuck-tail termination.

\** `ablation_no_material_cap/open200` avg ms computed from `timing_ms.total_ms` over the 190 successful generations (no `generation_summary.json` because run was interrupted).

## Reliability/Failure Notes
### Timeouts and stuck-tail behavior
Observed generation hard timeouts:
- baseline single100: `b5c816f9-08d6-41ea-a5a4-1e06ce0acd4f`
- no-material-cap single100: `2dcc67c3-e597-485a-81e4-fbb8226880c0`
- no-material-cap open200: `4d51932a-0d08-4512-8cd1-9dae6d68f695`

`no-material-cap/open200` entered a late stuck-tail state (high CPU, no output growth). The run was terminated and scored from produced outputs to avoid blocking indefinitely.

Failed query (hard timeout after retry):
- `4d51932a-0d08-4512-8cd1-9dae6d68f695`
- Question: "Which operational bottlenecks or dependencies does APH (APH) explicitly acknowledge in 2026, and how could they impact future results? Cite sources."
- Captured output: no draft/final answer and empty tool trace on failure row.

## Why Helpfulness Is Still High: Failure Inspection
A direct audit of baseline runs shows helpfulness failures are dominated by refusal-style outputs for out-of-index tickers, not primarily by weak synthesis on indexed names.

### Failure decomposition (baseline_post_fix)
Using `review.csv` + `generations.jsonl` in the three baseline runs:
- `single100`: `21` helpfulness fails; `20/21` (`95.2%`) are refusal-style (`"I can't answer because these tickers are not indexed"`).
- `multi60`: `30` helpfulness fails; `30/30` (`100%`) are refusal-style.
- `open200`: `56` helpfulness fails; `56/56` (`100%`) are refusal-style.
- Combined: `107` helpfulness fails; `106/107` (`99.1%`) are refusal-style.

Most frequent rejected tickers in helpfulness-fail rows:
- `MSFT` (`26`)
- `TSLA` (`24`)
- `META` (`21`)
- `AMZN` (`21`)
- `AAPL` (`19`)

### Concrete examples
#### Example A: open-ended fail driven by out-of-index refusal
- run: `eval/results_revamp/full_suite_ablation/eval_run.full_suite_ablation_20260220_022028.baseline_best.open200.normal.tools12.norefine.20260220_024910`
- query_id: `2fb4b736-656f-422f-a9a7-7745c8a7ab37`
- question: "What were the main stated drivers of profitability changes for TSLA (TSLA) in 2026, and which of them look persistent versus temporary? Cite sources."
- answer: refusal (`TSLA` not indexed).
- judge outcome: helpfulness fail; rationale says question was not addressed and no analysis/citations were provided.

#### Example B: comparison fail where one ticker is out-of-index
- run: `eval/results_revamp/full_suite_ablation/eval_run.full_suite_ablation_20260220_022028.baseline_best.multi60.normal.tools12.norefine.20260220_024054`
- query_id: `a57210b5-b1dc-4b54-bd6f-8b12712c6c46`
- question: "In 2025, how do AMZN (AMZN) and LITE (LITE) differ in strategy and competitive positioning?"
- answer: refusal (`AMZN` not indexed), no partial analysis for `LITE`.
- judge outcome: helpfulness fail; rationale highlights missing comparative analysis and missing sources.

#### Example C: factual fail from out-of-index refusal
- run: `eval/results_revamp/full_suite_ablation/eval_run.full_suite_ablation_20260220_022028.baseline_best.single100.normal.tools12.norefine.20260220_022029`
- query_id: `cf2cf7a8-aa09-4aa9-9d0b-7fb911cfbf0b`
- question: "What was MSFT's net income in its 10-K filed 2025-07-30?"
- answer: refusal (`MSFT` not indexed).
- judge outcome: helpfulness fail; rationale says the request was not answered.

#### Example D: genuine indexed-answer quality miss (non-refusal)
- run: `eval/results_revamp/full_suite_ablation/eval_run.full_suite_ablation_20260220_022028.baseline_best.single100.normal.tools12.norefine.20260220_022029`
- query_id: `cdcab831-39b6-4154-810a-279596cbe4d5`
- question: "What was GOOGL's net income in its 10-Q filed 2025-04-25?"
- answer: indexed ticker, but model claimed net income was not explicitly stated.
- judge outcome: helpfulness fail; rationale says the filing excerpt did include net income and the answer was wrong/verbose.

### Conclusion from inspection
- The high helpfulness fail rate is mainly a **coverage mismatch** between eval queries and indexed ticker universe in this run, not solely a generation-quality collapse.
- Secondary issue (smaller): occasional extraction/reasoning misses on indexed questions (Example D).

### Action implications
1. Expand index/query coverage alignment (ingest `MSFT`, `TSLA`, `META`, `AMZN`, `AAPL`) or split metrics into `in_index` vs `out_of_index` buckets.
2. For mixed comparison queries (one indexed, one not), return partial answer for indexed ticker plus explicit limitation note instead of hard refusal.
3. Keep separate tracking for true synthesis misses on indexed queries (like Example D), since these are the errors that retrieval/prompt improvements should target.

## Interpretation
### 1) Fixed planner routing materially improved baseline quality
The large baseline open200 improvement versus the flawed-planner run strongly indicates the previous spike in helpfulness/faithfulness failures was mostly routing-induced, not a pure retrieval/generation quality collapse.

### 2) Reranker-off is mixed, not a clear win
- `single100`: reranker-off improved open-ended faithfulness (`0.1034 -> 0.0333`) and latency.
- `open200`: reranker-off worsened both open-ended fail rates (`0.1200 -> 0.1500`, `0.2800 -> 0.2850`).
- `multi60`: slight tradeoff (`comparison fail` improves a bit; `comparison helpfulness` worsens a bit).

Conclusion: current evidence does not support globally disabling reranker for e2e default behavior.

### 3) Removing material-point cap is net negative
- Quality generally degrades (single and open).
- Latency worsens substantially (especially `multi60`, and partial `open200` shows much higher mean time and more retries).

Conclusion: keep the material cap enabled.

## Recommended Default (post-fix)
Based on this rerun set:
- Keep `baseline_best` as default.
- Keep reranker enabled.
- Keep material-point cap enabled.
- Keep timeout+retry policy (`350s`, `1` retry), but add better stuck-tail handling at runner level (future work: per-request watchdog + salvageable partial completion checkpoints).

## Repro / Commands Used
Primary launcher:
- `bash agent_logs/scripts/20260219_2358_run_full_suite_rerank_material_ablation.sh`

After interruption of `ablation_no_material_cap/open200`, scoring was completed manually:
- `python -m scripts.score_eval --run-dir eval/results_revamp/full_suite_ablation/eval_run.full_suite_ablation_20260220_022028.ablation_no_material_cap.open200.normal.tools12.norefine.20260220_042421 --judge-workers 12 --judge-context-chars 80000 --judge-timeout-s 350 --judge-max-retries 1`

# ROOT CAUSE OF TICKER MISMATCH:

- Verified cause: `.env` contained a stale `FINRAG_DOC_INDEX_PATH` (`exp__chunk_1024_o128_tokenizer__ctx_none__index_m24_ef200`), and the benchmark launcher used:
  - `DOC_INDEX_PATH="${FINRAG_DOC_INDEX_PATH:-<expected-512-profile-path>}"`
- Because `FINRAG_DOC_INDEX_PATH` was already set, the launcher silently selected the wrong doc index, even though the eval query sets were built for `eval_revamp_combined_512_20260217`.
- Evidence:
  - runtime command logs showed `--doc-index-path ./data/ingest_profiles/exp__chunk_1024_o128_tokenizer__ctx_none__index_m24_ef200/.../doc_index.jsonl`;
  - `.env` had `FINRAG_DOC_INDEX_PATH=./data/ingest_profiles/exp__chunk_1024_o128_tokenizer__ctx_none__index_m24_ef200/sec_filings_md_secparser/doc_index.jsonl`;
  - benchmark query files were `eval_queries_combined512_*_20260217.jsonl`, which are tied to the 512 ingest profile.
- Prevention implemented:
  - eval launchers now resolve doc index from ingest profile by default and **ignore** stale `.env` `FINRAG_DOC_INDEX_PATH` unless an explicit override is provided via `DOC_INDEX_PATH` (or `FINRAG_DOC_INDEX_PATH_OVERRIDE`);
  - `.env.example` no longer sets `FINRAG_DOC_INDEX_PATH` to avoid accidental drift.

## Update: Fixed-Settings Baseline Rerun (Interrupted by time)

This entry logs the latest rerun that used the fixed profile/path wiring (`full_suite_ablation_fixed_20260220_124150`).

### Run artifacts
- single100: `eval/results_revamp/full_suite_ablation/eval_run.full_suite_ablation_fixed_20260220_124150.baseline_best.single100.normal.tools12.norefine.20260220_124205`
- multi60: `eval/results_revamp/full_suite_ablation/eval_run.full_suite_ablation_fixed_20260220_124150.baseline_best.multi60.normal.tools12.norefine.20260220_125759`
- open200 (interrupted): `eval/results_revamp/full_suite_ablation/eval_run.full_suite_ablation_fixed_20260220_124150.baseline_best.open200.normal.tools12.norefine.20260220_131312`

### Metrics captured before stop
| Slice | Status | Generation | Avg gen total ms | Key fail rates |
|---|---|---:|---:|---|
| single100 | complete + scored | 100 / 0 | 55,657 | factual `0.0857`, factual helpfulness `0.0286`, open faithfulness `0.1000`, open helpfulness `0.0000`, distractor focus `0.0667`, distractor helpfulness `0.0000` |
| multi60 | complete + scored | 60 / 0 | 141,083 | comparison `0.0000`, comparison helpfulness `0.0000` |
| open200 | interrupted (not scored) | 24 generated rows | n/a | run manually stopped before scoring |

### Bootstrap 95% confidence intervals for captured fail rates
Bootstrap configuration:
- resamples: `20,000`
- seed: `42`
- source artifact: `agent_logs/reports/20260220_fixed_planner_baseline_bootstrap_ci.json`

| Metric | n | fail rate | bootstrap 95% CI |
|---|---:|---:|---:|
| single100 factual fail | 35 | 0.0857 | [0.0000, 0.2000] |
| single100 factual helpfulness fail | 35 | 0.0286 | [0.0000, 0.0857] |
| single100 open faithfulness fail | 30 | 0.1000 | [0.0000, 0.2000] |
| single100 open helpfulness fail | 30 | 0.0000 | [0.0000, 0.0000] |
| single100 distractor focus fail | 15 | 0.0667 | [0.0000, 0.2000] |
| single100 distractor helpfulness fail | 15 | 0.0000 | [0.0000, 0.0000] |
| multi60 comparison fail | 60 | 0.0000 | [0.0000, 0.0000] |
| multi60 comparison helpfulness fail | 60 | 0.0000 | [0.0000, 0.0000] |

Note:
- For all-zero empirical fail rates, nonparametric bootstrap returns `[0, 0]` because every resample remains all-zero. This reflects the observed sample; it does not imply true population uncertainty is exactly zero.

### Notes
- Runner settings for completed slices: `concurrency=12`, `query_timeout_s=350`, `query_max_retries=1`, retry multiplier `1.25`, cap `600`.
- `open200` was intentionally stopped early due time constraints; no judge metrics are available for this partial run.
