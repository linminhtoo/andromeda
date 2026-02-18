# Product Improvement Execution Plan (Post-Benchmark) - 2026-02-18

This plan maps `FUTURE_WORKS.md` into concrete near-term engineering changes that are measurable and demo-friendly for hiring-manager review.

## Selection criteria
- Customer-visible value in analyst workflows (trust, speed, auditability).
- Low-to-moderate implementation risk in current code architecture.
- Measurable with existing eval harness.

## Selected improvements (to implement after frontier benchmark completes)

### 1) Adaptive retrieval budget scheduler (query-complexity aware)
- Why customer-facing:
  - simple metric lookups should return faster;
  - complex narrative/comparison questions should preserve depth.
- Current gap in code:
  - static `top_k_retrieve/top_k_rerank` from preset for all queries.
- Proposed change:
  - add per-query retrieval budget policy in `RAGService` based on lightweight signals:
    - comparison question,
    - narrative intent,
    - explicit year/period constraints,
    - ticker cardinality.
  - keep hard caps bounded by preset to avoid runaway latency.
- Where:
  - `src/andromeda/query/runtime.py`
  - optionally `src/andromeda/llm/generation_controls.py` (policy defaults)
- How to measure:
  - latency (`p50/p95`, throughput qps) vs faithfulness/helpfulness and comparison fail rates.

### 2) Tool-first numeric routing hardening with explicit fallback reasons
- Why customer-facing:
  - reduces obvious numeric mistakes and improves explainability.
- Current gap in code:
  - routing exists, but fallback observability can be clearer for audits.
- Proposed change:
  - enrich tool-routing trace with deterministic fallback reason codes:
    - `tool_disabled`, `no_actionable_tool_results`, `period_scoped_requires_rag`, etc.
  - optionally include a compact `execution_policy` block in response payload.
- Where:
  - `src/andromeda/query/runtime.py`
  - `src/andromeda/query/conversation.py` / API response surfaces if needed.
- How to measure:
  - numeric-intent subset: tool usage rate, factual numeric accuracy, latency.

### 3) Prompt-prefix stabilization for better cacheability and consistency
- Why customer-facing:
  - lower steady-state latency/cost in repeated workflows;
  - more stable answer style.
- Current gap in code:
  - prompt sections are built dynamically but can be made more consistently ordered.
- Proposed change:
  - normalize prompt section ordering and static-prefix boundaries in `qa.py` builders.
  - keep dynamic content (`question/context/tool context`) strictly in trailing blocks.
- Where:
  - `src/andromeda/llm/qa.py`
- How to measure:
  - local proxy: token lengths + latency variance across repeated prompts;
  - eval proxy: no quality regression.

## Deferred improvements (documented, not immediate)
- ANN runtime knob (`ef_search`) in `src/andromeda/retrieval/db.py` TODO.
- Sparse method swap (`bm25` vs `fts`) with dedicated index rebuild cycle.
- Judge ensemble/bootstrap CI integration into default scoring output.
