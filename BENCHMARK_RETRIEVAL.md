# Benchmark: Retrieval + Rerank Quality (Reduced-Heuristics Branch)

## 1) Scope
This report continues from the completed 300-sample manual retrieval audit and closes the retrieval-focused evaluation workstream.

Primary goals:
- quantify retriever vs reranker behavior,
- quantify evidence-support quality on open-ended answers,
- audit retrieval relevance with non-circular manual labels (Codex reasoning, not judge-LLM),
- calibrate weak labels against manual labels.

All runs below use the same reduced-heuristics full-suite manifest:
- `eval/results_revamp/full_suite/reduced_heuristics_full_retry4_envoverride_20260218_195034.manifest.json`

## 2) Experiments Run

| ID | Experiment | Input artifacts | Output artifacts | What it measures |
|---|---|---|---|---|
| E1 | Factual retrieval/rerank IR metrics (`single100`) | `eval_run.reduced_heuristics_full_retry4_envoverride_20260218_195034.single100.normal.tools12.norefine.20260218_195034` | `retrieval_rerank_metrics.json`, `retrieval_rerank_metrics.csv`, `retrieval_nli_claim_support.csv` | Pre vs post rerank MRR/hit/precision/recall using factual gold evidence anchors |
| E2 | Open-ended NLI evidence support (`open200`) | `eval_run.reduced_heuristics_full_retry4_envoverride_20260218_195034.open200.normal.tools12.norefine.20260218_202301` | `retrieval_rerank_metrics.json`, `retrieval_nli_claim_support.csv` | Claim support / contradiction / unsupported rates |
| E3 | Multi slice retrieval pass (`multi60`) | `eval_run.reduced_heuristics_full_retry4_envoverride_20260218_195034.multi60.normal.tools12.norefine.20260218_200838` | `retrieval_rerank_metrics.json` | Completeness check for full-suite parity (no factual/open-ended rows in this slice) |
| E4 | Retrieval candidate pool build | all three run dirs above | `eval/results_revamp/full_suite/reduced_heuristics_full_retry4_envoverride_20260218_195034.retrieval_pool.csv`, `.stats.json` | pooled chunk candidates for manual relevance auditing |
| E5 | Manual relevance audit (300 rows) | `...retrieval_pool.sample300.csv` | `...retrieval_pool.sample300.codex_manual.csv` | Human-proxy relevance labels via Codex reasoning (non-circular) |
| E6 | Weak-label calibration | `...sample300.codex_manual.csv` | `...sample300.calibration.json` | Weak-label precision/recall/alignment vs manual labels |
| E7 | Manual audit summary rollup | `...sample300.codex_manual.csv` | `agent_logs/reports/retrieval_eval_20260218/manual_sample300_summary.json`, `.md` | relevance prevalence, pre/post membership, rank movement, top-k relevance slices |

## 3) Core Results

### 3.1 Retriever vs reranker on factual anchors (E1)

| Metric | Pre-rerank | Post-rerank | Delta |
|---|---:|---:|---:|
| factual_n | 34 | 34 | - |
| chunk MRR | 0.3092 | 0.1743 | -0.1349 |
| chunk win rate | - | - | 0.1765 |
| chunk precision@5 | 0.1118 | 0.0647 | -0.0471 |
| chunk precision@10 | 0.0647 | 0.0471 | -0.0176 |
| chunk precision@25 | 0.0294 | 0.0282 | -0.0012 |
| chunk recall@25 | 0.7353 | 0.7059 | -0.0294 |
| doc MRR | 1.0000 | 1.0000 | 0.0000 |

Interpretation:
- On factual gold-anchor queries, current reranking is net negative on chunk-level relevance concentration.
- Doc-level MRR is saturated at 1.0 and is not discriminative for this run.

### 3.2 NLI claim support on open-ended generations (E1/E2)

| Slice | n_open_ended_scored | support_rate | contradiction_rate | unsupported_rate |
|---|---:|---:|---:|---:|
| `single100` subset | 30 | 0.1000 | 0.3958 | 0.5042 |
| `open200` | 120 | 0.1292 | 0.4115 | 0.4594 |

Interpretation:
- Support is low and contradiction/unsupported are high.
- This aligns directionally with remaining faithfulness pressure points in answer-level evals.

### 3.3 Multi slice parity check (E3)

`multi60` has no factual or open-ended rows, so retrieval IR/NLI outputs are expectedly `NaN`/empty for these specific metric families.

## 4) Manual 300-Sample Relevance Audit (E5/E7)

Manual labels are from Codex reasoning on each row, not from the judge LLM.

Source:
- `eval/results_revamp/full_suite/reduced_heuristics_full_retry4_retrieval_pool.sample300.codex_manual.csv`

Summary:
- `n_labeled = 300`
- overall positive relevance rate = `0.4167`

By query kind:

| Kind | n | n_positive | positive_rate |
|---|---:|---:|---:|
| factual | 140 | 19 | 0.1357 |
| open_ended | 90 | 53 | 0.5889 |
| comparison | 55 | 44 | 0.8000 |
| distractor | 15 | 9 | 0.6000 |

Pre/post membership buckets:

| Bucket | n | n_positive | positive_rate |
|---|---:|---:|---:|
| both pre+post | 195 | 74 | 0.3795 |
| pre-only | 53 | 26 | 0.4906 |
| post-only | 52 | 25 | 0.4808 |

Relevant-rank movement (rows present in both pre and post, relevance=1):
- n=74, promoted=32, demoted=37, unchanged=5, avg delta(post-pre)=+0.0676

By kind (same movement view):

| Kind | n | promoted | demoted | unchanged | avg_delta(post-pre) |
|---|---:|---:|---:|---:|---:|
| factual | 15 | 4 | 9 | 2 | +2.8000 |
| open_ended | 38 | 19 | 17 | 2 | -1.8421 |
| comparison | 17 | 6 | 10 | 1 | +3.4118 |
| distractor | 4 | 3 | 1 | 0 | -6.2500 |

Sample top-k relevance slices (not an unbiased absolute P@k estimator; useful as directional diagnostics):

| Phase | k | n_rows_in_slice | n_positive | positive_rate |
|---|---:|---:|---:|---:|
| pre | 5 | 63 | 40 | 0.6349 |
| post | 5 | 64 | 37 | 0.5781 |
| pre | 10 | 128 | 60 | 0.4688 |
| post | 10 | 134 | 71 | 0.5299 |

Interpretation:
- At very early ranks (top-5), audited relevance is lower post-rerank than pre-rerank.
- At top-10, post-rerank recovers and slightly exceeds pre-rerank in this sample.
- Factual and comparison rows show more demotions than promotions, consistent with E1 factual-anchor degradation.

## 5) Weak-Label Calibration (E6)

Source:
- `eval/results_revamp/full_suite/reduced_heuristics_full_retry4_retrieval_pool.sample300.calibration.json`

Threshold: weak relevance >= 0.5 => relevant.

| Metric | Value |
|---|---:|
| n | 140 |
| accuracy | 0.1357 |
| precision_1 | 0.1357 |
| recall_1 | 1.0000 |
| f1_1 | 0.2390 |
| balanced_accuracy | 0.5000 |
| tp / fp / tn / fn | 19 / 121 / 0 / 0 |

Interpretation:
- Current weak labels are recall-maximal but extremely low precision (many false positives).
- They are suitable as high-recall candidate generation tags, not as ground-truth proxies for precision-sensitive decisions.

## 6) Surprising Findings and Hypotheses

1. Reranking currently hurts factual chunk concentration.
- Evidence: negative chunk MRR and precision deltas on factual anchors.
- Hypothesis: reranker objective overweights semantic fluency/contextual breadth vs exact numeric-evidence grounding.

2. Doc-level metrics saturate and hide problems.
- Evidence: doc MRR fixed at 1.0 while chunk metrics degrade.
- Hypothesis: relevant document is often retrieved, but best evidence chunk inside that document is not prioritized.

3. Weak labels are not precision-usable.
- Evidence: 121 FP out of 140 weak-positive rows in calibrated subset.
- Hypothesis: doc-match score 0.7 is too permissive for relevance labeling in factual settings.

4. NLI flags substantial unsupported/contradicted claim mass.
- Evidence: contradiction ~0.40 and unsupported ~0.46-0.50.
- Hypothesis: long answers contain extrapolative claims beyond retrieved evidence granularity.

## 7) Actionable Next Steps

1. Rerank objective/feature tuning with factual-priority constraints.
- Add hard/soft boosts for period-aligned numeric/table chunks in rerank scoring.
- Re-run E1 and require non-negative delta on chunk MRR and P@5 before promotion.

2. Improve weak-label scheme.
- Replace binary doc-match surrogate with graded weak labels including period/type alignment.
- Keep manual 300+ audits for calibration and CIs.

3. Expand manual audit slices where signal is weakest.
- Increase factual sample beyond 140 rows and stratify by rerank disagreement bands.

4. Keep this retrieval benchmark as a standing gate.
- Run E1+E5+E6 for major retrieval/prompt changes and block merges on consistent factual rerank regressions.

## 8) Repro Commands

Scripts executed:
- `agent_logs/scripts/eval/20260218_211000_run_retrieval_pool_and_metrics.sh`
- `agent_logs/scripts/eval/20260218_215100_eval_retrieval_multi60.sh`
- `agent_logs/scripts/eval/20260218_215700_summarize_retrieval_manual_sample.sh`

Calibration command:
- `source .venv/bin/activate && python scripts/calibrate_eval_metrics.py --labels-csv eval/results_revamp/full_suite/reduced_heuristics_full_retry4_retrieval_pool.sample300.codex_manual.csv --human-col human_relevance --weak-col weak_relevance --weak-threshold 0.5 --n-bootstrap 2000 --out-json eval/results_revamp/full_suite/reduced_heuristics_full_retry4_retrieval_pool.sample300.calibration.json`
