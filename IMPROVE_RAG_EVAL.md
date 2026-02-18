# Improve RAG Evaluation Methodology (Retrieval + Reranking Focus)

Date: 2026-02-18
Scope: Planning only (no code changes in this task)

## 1) Problem Statement

Your current eval stack is strong for end-to-end answer quality and judge operations, but it still under-instruments subsystem quality, especially:

- retrieval quality before reranking
- reranker uplift vs. non-reranked candidates
- evidence utilization (did the model use retrieved evidence correctly?)

This aligns with the critique in `CRITIQUES.md` and current pipeline behavior described in `README_EVAL.md` and `src/andromeda/eval/scoring.py`.

## 2) Recommendation in One Line

Use a **hybrid eval strategy**:

- keep LLM judge evals for final-answer/product quality
- add cheap, high-throughput **retrieval/rerank subsystem evals** (IR metrics + chunk relevance)
- add **NLI-based claim support checks** as a scalable middle layer
- calibrate all auto metrics with a small, targeted human-labeled slice

This avoids over-optimizing to one judge while keeping annotation cost low.

## 3) Why This Is the Right Direction

- RAG evaluation is inherently multi-component (retrieval quality, faithfulness, answer quality), not a single pass/fail axis [6], [7].
- LLM judges are useful but biased (position/verbosity/self-enhancement); they should be calibrated and not be the only optimization target [4], [12], [13], [14].
- Reranking is effective in many IR settings but should be measured explicitly with pre/post deltas, not inferred indirectly [10], [11].
- Long-context systems often under-use relevant middle-context evidence; early-rank relevance matters for practical quality [15].
- NLI-style consistency checks are practical and can work well with modest task-specific data [5], [16], [17].

## 4) Target Evaluation Architecture

### Layer A: Retriever Quality (Pre-rerank)

Measure on `retrieved_chunks` (already available in eval generation artifacts):

- `Recall@k` (chunk/doc)
- `Precision@k` (chunk)
- `MRR@k`
- `nDCG@k` (when graded relevance exists)
- `Ticker coverage` and `period coverage` for finance-specific retrieval

Primary outcome: “Does retrieval surface the right evidence at all?”

### Layer B: Reranker Quality (Post-rerank vs Pre-rerank)

Directly compare `top_chunks` (post-rerank) against `retrieved_chunks`:

- `Delta MRR`, `Delta Recall@k`, `Delta Precision@k`, `Delta nDCG@k`
- per-query win/loss/tie rate for reranking
- rank shift of first relevant chunk (how much relevance is moved toward the front)

Primary outcome: “How much precision gain does reranking produce, and where?”

### Layer C: Evidence Utilization (Answer conditioned on retrieved context)

For generated answers:

- claim extraction -> claim-to-evidence support scoring
- support via NLI and/or judge-backed entailment checks
- report support rate / contradiction rate / unsupported-claim rate

Primary outcome: “Given retrieved context, did generation use evidence correctly?”

### Layer D: Final Answer (Existing Judge Layer)

Keep your current judge suite for end-user quality, but treat it as one layer among several, not the sole optimization objective.

## 5) Low-Annotation Data Strategy

### 5.1 Start from existing assets (zero extra labeling upfront)

Leverage current eval artifacts:

- `eval/eval_queries_*` (already diverse by kind)
- existing factual gold evidence metadata
- existing generation outputs containing both pre/post rerank chunks

This gives immediate subsystem metrics with minimal additional work.

### 5.2 Build a pooled relevance set (annotation-efficient)

For each query, pool candidates from:

- top-N pre-rerank
- top-N post-rerank
- optional ablations (different retrieval settings)

Then label only pooled candidates instead of full corpus judgments.

### 5.3 Use weak/silver labels first, then calibrate

Initial labels can come from:

- existing gold evidence anchors (factual queries)
- NLI support against reference answer/claims
- optional lightweight LLM labeler for ambiguous cases

Then calibrate with a small human-labeled set (few hundred items), following ARES-style low-label correction principles (PPI) [8].

### 5.4 Human labeling budget recommendation

- 250-400 query-chunk judgments initially
- stratify by:
  - query type (factual/open-ended/comparison)
  - reranker disagreements
  - high-impact finance cases (numeric/table/period-sensitive)

This is enough to calibrate thresholds and estimate metric error bars without a large annotation project.

## 6) Metric Set to Add

### Retrieval/Rerank core metrics

- `P@5`, `P@10`
- `R@10`, `R@20`, `R@50`
- `MRR@10`, `MRR@25`
- `nDCG@10`, `nDCG@25` (if graded labels available)
- reranker uplift deltas and win-rate

### Claim/evidence metrics

- claim support precision
- claim contradiction rate
- unsupported-claim rate
- context utilization rate (claim supported by retrieved chunks)

### Statistical discipline

- paired bootstrap CIs (or paired randomization tests) on key deltas
- publish confidence intervals in reports
- reject “wins” where CI overlaps zero

## 7) Decision: Judge vs BERT/NLI?

Do **both**, with role separation:

- Judge: product-level quality and nuanced rubric checks
- NLI: high-throughput, lower-cost, claim/chunk support checks for subsystem loops

Operationally:

- run NLI on every eval sample
- run judge on full or stratified subset (depending on cost)
- weekly calibrate judge and NLI against human-labeled slice

This gives speed + robustness and reduces judge-only Goodhart risk.

## 8) Phased Implementation Plan

Each phase is independently testable and shippable.

### Phase 0: Baseline Instrumentation and Definitions

Goal:

- lock metric definitions and baseline numbers for retrieval and reranking from existing runs

Acceptance criteria:

- one report generated from existing artifacts with pre/post rerank metrics
- metric definitions documented with formulas
- baseline tables stored under `agent_logs/reports/`

### Phase 1: Retrieval/Rerank Evaluator (No Human Labels Required)

Goal:

- compute IR metrics directly from current eval data (gold where available + ID-based proxies)

Acceptance criteria:

- CLI command produces retrieval/rerank score summary JSON
- includes reranker deltas and per-query win/loss/tie
- integrated into eval reporting flow

### Phase 2: Claim-Level Evidence Support (NLI First)

Goal:

- add claim support/contradiction metrics at answer-evidence level

Acceptance criteria:

- per-answer claim support statistics are produced
- metrics run in batch at acceptable cost/latency
- metrics appear in dashboard/report alongside judge metrics

### Phase 3: Human Calibration + PPI Correction

Goal:

- calibrate auto metrics with small human annotation set and bias-correct estimates

Acceptance criteria:

- labeled calibration set committed under `eval/` data path
- calibration report includes precision/recall and agreement stats
- corrected estimates + CIs reported for key metrics

### Phase 4: CI/Regression Gates

Goal:

- prevent silent retrieval/rerank regressions

Acceptance criteria:

- PR/nightly gate fails when retrieval/rerank metrics regress beyond thresholds
- threshold policy documented in `README_EVAL.md`
- changelog policy updated for eval methodology changes

## 9) Proposed File Plan (For Future Implementation)

`files_to_change`:

- `scripts/score_eval.py`
- `scripts/run_eval.py` (only if additional artifact fields are needed)
- `src/andromeda/eval/scoring.py`
- `src/andromeda/eval/report.py`
- `src/andromeda/eval/schema.py`
- `README_EVAL.md`
- `CHANGELOG.md`

`new_files`:

- `src/andromeda/eval/retrieval_metrics.py`
- `src/andromeda/eval/rerank_metrics.py`
- `src/andromeda/eval/evidence_support.py`
- `scripts/eval_retrieval.py`
- `scripts/build_retrieval_label_pool.py`
- `scripts/calibrate_eval_metrics.py`
- `eval/retrieval_labels/*.jsonl`
- `agent_logs/reports/retrieval_rerank_eval_*.md`

## 10) Suggested Initial Thresholds (Tune After Baseline)

- reranker `Delta P@5` must be > 0 with 95% CI excluding 0
- reranker win-rate >= 55%
- no regression > 2% absolute in `R@20` on core factual subset
- unsupported-claim rate must not worsen while optimizing retrieval precision

## 11) Risks and Mitigations

- Risk: Overfitting to silver labels
  Mitigation: keep human calibration slice and rotate disagreement samples.

- Risk: NLI misses finance-specific nuances (units/periods)
  Mitigation: add finance-targeted calibration examples and targeted failure audits.

- Risk: Metric sprawl
  Mitigation: keep one decision dashboard with a small, fixed “release gate” subset.

## 12) Suggested Future Add-ons (Not in current scope)

- Adversarial retrieval tests (hard distractors, near-miss tables, conflicting filings)
- Section-aware retrieval diagnostics (MD&A vs Risk Factors vs footnotes)
- Counterfactual rerank tests (swap top chunk order to quantify context-position sensitivity)

## Sources

1. Internal critique: `CRITIQUES.md`
2. Internal eval runbook: `README_EVAL.md`
3. Eugene Yan, *Evaluating Long-Context Question & Answer Systems*: https://eugeneyan.com/writing/qa-evals/
4. Eugene Yan, *Evaluating the Effectiveness of LLM-Evaluators*: https://eugeneyan.com/writing/llm-evaluators/
5. Eugene Yan, *Task-Specific LLM Evals that Do & Don't Work*: https://eugeneyan.com/writing/evals/
6. RAGAS paper (arXiv): https://arxiv.org/abs/2309.15217
7. RAGAS metrics docs (context precision/recall/faithfulness): https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/context_precision/ , https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/context_recall/ , https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/faithfulness/
8. ARES (NAACL 2024): https://aclanthology.org/2024.naacl-long.20/
9. RAGChecker (paper + repo): https://arxiv.org/abs/2408.08067 , https://github.com/amazon-science/RAGChecker
10. BEIR benchmark: https://arxiv.org/abs/2104.08663
11. Sentence Transformers reranker docs: https://www.sbert.net/examples/cross_encoder/training/rerankers/README.html
12. MT-Bench / LLM-as-judge biases: https://arxiv.org/abs/2306.05685
13. Position bias in judges: https://arxiv.org/abs/2406.07791
14. Bias catalog for LLM-as-judge: https://arxiv.org/abs/2410.02736
15. Lost in the Middle: https://arxiv.org/abs/2307.03172
16. Self-RAG: https://arxiv.org/abs/2310.11511
17. SummaC (NLI consistency): https://arxiv.org/abs/2111.09525
18. Example NLI model card (`cross-encoder/nli-deberta-v3-large`): https://huggingface.co/cross-encoder/nli-deberta-v3-large
