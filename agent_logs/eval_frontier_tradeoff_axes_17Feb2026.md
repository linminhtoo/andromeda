# Frontier Mapping Plan: Additional Tradeoff Axes

Date: 2026-02-17

This document lists high-value tradeoff studies to run next. No experiments were executed in this step.

## Priority A: Retrieval Quality vs Latency

### 1) Retrieval depth and rerank depth
- Variables:
  - `top_k_retrieve`: 20, 30, 40, 60
  - `top_k_rerank`: 10, 18, 25, 35
- Why:
  - Controls recall and context noise directly.
- Metrics to watch:
  - faithfulness fail, factual correctness fail, p95 latency.
- Expected frontier behavior:
  - diminishing quality returns after a point, but latency keeps rising.

### 2) Diversity-aware retrieval (MMR)
- Variables:
  - enable/disable MMR
  - `lambda`: 0.3, 0.5, 0.7
  - MMR candidate pool size: 40, 60, 80
- Why:
  - Reduces near-duplicate chunks and improves evidence coverage.
- Metrics to watch:
  - open-ended faithfulness fail, gold-chunk hit rank, latency overhead.
- Expected frontier behavior:
  - better faithfulness at low-to-moderate latency increase.

### 3) Sparse/dense weighting
- Variables:
  - sparse-only, dense-only, hybrid weighted mixes (for example 0.3/0.7, 0.5/0.5, 0.7/0.3)
- Why:
  - Numeric/fact lookups may benefit from lexical precision.
- Metrics to watch:
  - factual numeric accuracy, factual correctness fail, retrieval recall.

## Priority B: Generation Control Frontier

### 4) Draft/final token budgets
- Variables:
  - draft max tokens: 2200, 3200, 4200
  - final max tokens: 2200, 3200, 4200
- Why:
  - Longer budgets can reduce truncation-driven errors but hurt latency.
- Metrics to watch:
  - helpfulness fail, faithfulness fail, p95 latency, timeout rate.

### 5) Finance-tools-first gating policy
- Variables:
  - tool-first strict for numeric intents (on/off)
  - confidence threshold for tool fallback to RAG
- Why:
  - Numeric failures should drop when tool outputs are preferred over free-form generation.
- Metrics to watch:
  - factual numeric accuracy, factual correctness fail, tool-call rate, tool failure rate.

### 6) Query intent router sensitivity
- Variables:
  - classifier threshold for numeric vs open-ended vs refusal paths
- Why:
  - Better routing can improve both faithfulness and latency.
- Metrics to watch:
  - category confusion matrix, per-kind fail rates, end-to-end latency.

## Priority C: Judge Reliability and Stability

### 7) Judge prompt variants and calibration set
- Variables:
  - strictness wording, citation requirements, scoring rubric granularity
- Why:
  - judge prompt changes can shift reported metrics significantly.
- Method:
  - freeze generation outputs, iterate only judge prompts.
- Metrics to watch:
  - inter-judge agreement, volatility of fail rates, false positive/negative audits.

### 8) Judge model comparison
- Variables:
  - judge model A vs B (same rubric and context limits)
- Why:
  - validate metric robustness to judge model choice.
- Metrics to watch:
  - disagreement rate, category-specific drift.

## Priority D: Corpus and Data Frontier

### 9) Filing horizon depth
- Variables:
  - number of filings per ticker (last 2, 4, 6 quarters + latest annual)
- Why:
  - more history may improve coverage but increase retrieval confusion.
- Metrics to watch:
  - faithfulness fail, distractor/focus fail, retrieval latency.

### 10) Ticker universe breadth
- Variables:
  - 10, 20, 40 ticker sets with sector balance
- Why:
  - stress-test multi-entity confusion and retrieval precision.
- Metrics to watch:
  - multi-ticker faithfulness, focus fail, p95 latency.

## Suggested Execution Order
1. Retrieval depth x rerank depth grid.
2. MMR diversity settings at best depth pair.
3. Tool-first numeric routing policy.
4. Judge-only calibration loop on frozen generations.
5. Expanded ticker universe stress test.

## Minimal Reporting Template (for each future run)
- Experiment id and git commit hash
- Exact command line and key env vars
- Dataset ids and sample counts
- Latency: avg/p50/p95 and timeout/error counts
- Metrics by category
- 3-5 representative failure traces
- Decision: promote/reject + next action
