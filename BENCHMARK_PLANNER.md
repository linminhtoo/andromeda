# Benchmark: Planner Characteristics Evaluation

_Last updated: 2026-02-19_

## 1) Scope
This report benchmarks planner-side multi-label classification quality for query characteristics.

Goal:
- verify whether planner output correctly identifies all applicable query characteristics before answer generation.

Characteristics evaluated:
- `comparison`
- `market_data`
- `financial_metrics`
- `filing_narrative`
- `period_scoped`
- `simple_numeric`

Dataset:
- `eval/eval_queries_planner_characteristics_manual100_20260219.jsonl`
- 100 manually curated queries (not LLM-generated), with explicit labels and rationale per row.

## 2) Experiments Run

| ID | Experiment | Command/script | Output artifacts | Purpose |
|---|---|---|---|---|
| P1 | Planner generation run | `agent_logs/scripts/eval/20260219_205324_run_planner_eval_suite_live.sh` | `planner_predictions.jsonl`, `planner_prediction_summary.json` | Run planner on all 100 queries with timeout/retry controls |
| P2 | Planner scoring | `scripts/score_planner_eval.py` (invoked by P1) | `planner_scores.jsonl`, `planner_score_summary.json`, `planner_review.csv`, `planner_score_summary.md` | Compute exact/subset/precision/recall metrics and per-characteristic confusion |
| P3 | Failure-pattern analysis | `agent_logs/scripts/eval/20260219_205431_analyze_planner_eval_run.sh` | `agent_logs/reports/planner_eval_20260219/planner_eval_analysis_20260219_205341.json` | Aggregate mismatch patterns, tag-level slices, action errors |

Run directory:
- `eval/results_planner/planner_eval_run.planner_live_manual100_20260219_205341.20260219_205341`

## 3) Run Configuration

- workers: `12`
- planner timeout: `350s`
- planner retries: `1`
- queries run: `100`
- generation errors: `0`

Runtime summary:
- avg query latency: `2347.22 ms`
- wall time: `21404.30 ms`
- throughput: `4.67 queries/s`

## 4) Topline Results

### 4.1 Overall

| Metric | Value |
|---|---:|
| characteristic exact match rate | 0.6400 |
| expected-subset recall rate | 0.7600 |
| macro precision | 0.9117 |
| macro recall | 0.9033 |
| macro F1 | 0.8907 |
| micro precision | 0.9101 |
| micro recall | 0.8571 |
| micro F1 | 0.8828 |
| action accuracy (6 labeled action rows) | 0.6667 |

Interpretation:
- planner is generally precise and high-recall on most characteristics, but exact-match quality is limited by a concentrated error mode.

### 4.2 Per-Characteristic Breakdown

| Characteristic | Support | Precision | Recall | F1 | TP | FP | FN |
|---|---:|---:|---:|---:|---:|---:|---:|
| comparison | 22 | 0.9091 | 0.9091 | 0.9091 | 20 | 2 | 2 |
| market_data | 37 | 1.0000 | 0.9189 | 0.9577 | 34 | 0 | 3 |
| financial_metrics | 28 | 0.9032 | 1.0000 | 0.9492 | 28 | 3 | 0 |
| filing_narrative | 40 | 0.9500 | 0.9500 | 0.9500 | 38 | 2 | 2 |
| period_scoped | 28 | 0.8485 | 1.0000 | 0.9180 | 28 | 5 | 0 |
| simple_numeric | 34 | 0.7778 | 0.4118 | 0.5385 | 14 | 4 | 20 |

Key point:
- `simple_numeric` is the clear bottleneck (20 false negatives out of 34 support).

## 5) Failure Analysis

### 5.1 Dominant mismatch pattern
Top mismatch:
- `missing=simple_numeric | extra=-` occurred `20` times.

These misses are concentrated in queries labeled:
- `financial_metrics period_scoped simple_numeric` (20 rows)

Observed pattern:
- predicted set was consistently `financial_metrics period_scoped`, omitting `simple_numeric`.

Examples:
- `planner_eval_0023`: "What was AAPL's net income in 2025?"
- `planner_eval_0024`: "What was MSFT's total revenue in FY2024?"
- `planner_eval_0025`: "What was NVDA's gross margin in Q2 2025?"

### 5.2 Tag-level quality

| Tag group | n | exact_match_rate | subset_recall_rate |
|---|---:|---:|---:|
| `comparison filing_narrative` | 14 | 1.0000 | 1.0000 |
| `filing_narrative market_data` | 8 | 1.0000 | 1.0000 |
| `financial_metrics period_scoped analysis` | 8 | 1.0000 | 1.0000 |
| `market_data simple_numeric` | 14 | 0.8571 | 0.8571 |
| `market_data contextual` | 8 | 0.1250 | 1.0000 |
| `comparison market_data` | 6 | 0.5000 | 1.0000 |
| `financial_metrics period_scoped simple_numeric` | 20 | 0.0000 | 0.0000 |
| `clarification ambiguous_ticker` | 2 | 0.0000 | 0.0000 |

Interpretation:
- the planner usually includes core characteristics, but often adds/removes secondary tags in contextual market queries.
- the period-scoped numeric bucket is currently overfit to "financial metric trend" interpretation and misses direct numeric intent.

### 5.3 Action errors

Action-labeled rows: 6 (`4` refusal + `2` clarification-required)

Action mismatches (2):
- `planner_eval_0099`: expected `clarification_required`, predicted `refused`
- `planner_eval_0100`: expected `clarification_required`, predicted `refused`

Both are ambiguous watchlist/bank comparison prompts without explicit ticker names.

## 6) Surprising Observations

1. Planner throughput was high despite local vLLM setup.
- 100 planner calls completed in ~21.4s wall-clock with 12 threads and no failures.

2. `simple_numeric` under-classification is highly concentrated, not diffuse.
- 20 misses are effectively one repeated decision pattern, not random noise.

3. Prompt-level contradiction likely explains the biggest gap.
- In planner few-shot examples (`src/andromeda/query/runtime.py`), a direct numeric period question ("What was AAPL net income in 2025?") is labeled as `[financial_metrics, period_scoped]` without `simple_numeric`.
- That pattern mirrors the 20-row failure bucket almost exactly.

4. Action metric is unstable due low support.
- `action_accuracy=0.6667` is based on only 6 rows; this should not be over-interpreted.

## 7) Practical Recommendations

1. Fix planner few-shot labels before changing architecture.
- Align examples so direct period-scoped single-value metric queries include `simple_numeric`.

2. Expand action-labeled benchmark rows.
- Increase clarification/refusal-labeled rows from 6 to at least 30 to reduce metric variance.

3. Keep this planner eval as a standing gate.
- Require non-regression on:
  - `simple_numeric recall`
  - overall `exact_match_rate`
  - `expected_subset_recall_rate`

## 8) Repro

Run:
```bash
source .venv/bin/activate
agent_logs/scripts/eval/20260219_205324_run_planner_eval_suite_live.sh
```

Analyze:
```bash
source .venv/bin/activate
agent_logs/scripts/eval/20260219_205431_analyze_planner_eval_run.sh \
  eval/results_planner/planner_eval_run.planner_live_manual100_20260219_205341.20260219_205341
```
