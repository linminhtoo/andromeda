# Improve Retrieval Eval for Repeated Facts in SEC Filings

Date: 2026-02-20
Scope: Brainstorming only (no code changes in this task)

## 1) Problem

The current factual retrieval eval treats one chunk as the only gold target. In SEC filings, the same fact often appears in:

- multiple sections of one filing (summary, MD&A, footnotes, tables)
- multiple filings (10-K vs 10-Q, amended filings, year-over-year repeated statements)

This causes false negatives in retrieval eval: a system can retrieve correct evidence but still be marked wrong if it did not return the single annotated chunk.

## 2) Goal

Move from single-gold annotation to multi-positive, fact-centric evaluation that rewards retrieval of any valid evidence for the same fact.

## 3) Core Idea: Evaluate Facts, Not Single Chunks

For each factual query, define a `fact_id` and attach a set of relevant evidence chunks/documents.

- `fact_id` represents the semantic fact target (example components: ticker, metric, period, value, unit/scale)
- `relevant_chunk_ids` includes all chunks that explicitly state the same fact
- `relevant_doc_ids` includes all filings/documents containing the fact
- keep one `canonical_evidence` for traceability/debugging, but do not score only against it

## 4) Proposed Label Schema Upgrades

Add fields to factual ground truth:

- `fact_id: str`
- `canonical_evidence: EvidenceChunk`
- `alternate_evidence: list[EvidenceChunk]`
- `relevant_chunk_ids: list[str]`
- `relevant_doc_ids: list[str]`
- `relevance_by_chunk_id: dict[str, float]` (optional graded relevance)
- `fact_constraints`:
  - required period (fiscal year/quarter)
  - required unit/scale normalization
  - optional tolerance for numeric formatting/rounding

Use graded labels when useful:

- `3.0`: direct exact statement of the target fact
- `2.0`: semantically equivalent paraphrase with matching number/period
- `1.0`: partially useful supporting context (same metric but incomplete period/value)
- `0.0`: not relevant

## 5) Ground Truth Generation Improvements

### 5.1 Candidate Pooling (High Recall First)

For each factual query, build a pooled candidate set from:

- top-N pre-rerank chunks
- top-N post-rerank chunks
- lexical and dense retrieval variants
- optional query rewrites (metric synonyms, period variants)

This reduces annotation miss rate for duplicate facts.

### 5.2 Fact Canonicalization

Before grouping evidence, canonicalize numeric facts:

- normalize units/scales (USD, millions, billions)
- normalize period semantics (FY2024 vs year ended Dec 31, 2024)
- normalize metric aliases (revenue/net sales, operating income variants)

Then cluster candidates that map to the same canonical fact signature.

### 5.3 Automatic Positive Expansion (Silver Labels)

Starting from canonical evidence, auto-expand positives using strict checks:

- metric alias match
- normalized value match within tolerance
- period match
- optional entailment/NLI confirmation for ambiguous prose

Mark uncertain matches as `needs_review` rather than forcing labels.

### 5.4 Human Adjudication on Uncertainty

Use human review only for hard cases:

- conflicting values across sections
- ambiguous period references
- similar metrics that are not equivalent

This keeps cost manageable while improving label quality.

## 6) Retrieval Metrics to Prefer with Multi-Positive Labels

Once `relevant_chunk_ids` is available, prioritize set-based metrics:

- `Recall@k` (chunk and doc): primary success metric
- `Hit@k`: at least one relevant chunk found
- `MRR_any`: reciprocal rank of the first relevant chunk
- `MAP@k`: rewards finding multiple positives early
- `nDCG@k`: leverage graded relevance when available

Keep precision metrics, but interpret carefully in highly redundant corpora.

## 7) Reranker-Specific Metrics to Add

Beyond delta MRR:

- `positive_concentration@k`: fraction of top-k that are relevant
- `first_positive_rank_shift`: change in first relevant rank pre vs post
- `recall_preservation@k`: did reranking drop relevant chunks seen pre-rerank?
- `win/loss/tie` by query based on any-positive rank and nDCG

This measures whether reranking improves ordering without harming evidence coverage.

## 8) New Failure Modes to Explicitly Measure

- **Over-penalization of alternates**: retrieved equivalent fact but old single-gold eval marks miss
- **Temporal mismatch**: correct metric/value but wrong fiscal period
- **Cross-filing leakage**: value from different filing period retrieved as if correct
- **Near-miss metric confusion**: operating income vs net income, revenue vs gross profit

Add slice-level reporting for these categories.

## 9) Practical Dataset Construction Strategy

### Phase A: Backward-Compatible Expansion

- keep existing `golden_evidence`
- add `alternate_evidence` + `relevant_chunk_ids`
- update scorer to use set-based relevance while still supporting legacy rows

### Phase B: Graded Relevance

- introduce `relevance_by_chunk_id`
- compute nDCG/AP metrics in addition to binary metrics

### Phase C: Hard-Negative and Robustness Set

Create explicit challenge subsets:

- repeated facts in same filing
- repeated facts across filings
- numerically close but incorrect values
- period-shift traps (FY vs Q4)

Use these as regression gates for retriever/reranker changes.

## 10) Suggested Reporting Changes

For each run, publish:

- binary multi-positive metrics: recall/hit/MRR/MAP
- graded metrics: nDCG
- reranker uplift and recall-preservation
- slice metrics by query type and difficulty mode
- confidence intervals (paired bootstrap) for key deltas

This makes retrieval quality comparisons more trustworthy than single-gold scoring.

## 11) What Not to Do

- do not keep single-gold as the only target for factual retrieval
- do not rely only on answer-level judge scores to infer retrieval quality
- do not expand positives with loose semantic similarity alone (high false-positive risk)

## 12) Minimal Viable Next Step

If we want fast progress with limited effort:

1. Add `relevant_chunk_ids` to factual rows for a subset of queries.
2. Update scoring to treat any listed chunk as relevant.
3. Report `Recall@k`, `Hit@k`, `MRR_any` pre/post rerank.
4. Keep current fields for compatibility and compare old vs new scoring side-by-side.

