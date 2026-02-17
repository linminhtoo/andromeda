# FUTURE_WORKS

This roadmap is written for a forward-deployed engineering audience: customer outcomes first, with technical workstreams tied to measurable product impact.

## 1) Customer-First Product Lens

## Primary user archetypes
- Buy-side / sell-side analyst: needs trustworthy, citation-backed answers fast enough for interactive research.
- Investment banking / corp-dev associate: needs multi-company synthesis with comparable metrics and explicit assumptions.
- Internal AI platform owner: needs predictable cost/latency, robust guardrails, and operational visibility.

## Recurring customer pains observed
- Trust friction: users hesitate when answers are not clearly grounded in filing evidence.
- Numeric workflow friction: users ask simple numeric questions but model paths sometimes overuse free-form generation.
- Time-to-answer friction: long open-ended responses can be high quality but too slow for iterative analysis.
- Ops friction: regressions are hard to detect without stable, policy-backed service objectives.

## 2) North-Star Goals (12-Month)

- Reliability:
  - open-ended faithfulness **false-positive adjusted** fail rate <= 0.12 on curated open set.
  - factual correctness fail rate <= 0.04 on validated factual set.
- Speed:
  - p95 end-to-end response latency <= 45s for single-ticker normal mode.
  - p95 judge scoring latency <= 30s per case with batch throughput targets.
- Usefulness:
  - helpfulness fail <= 0.02 across factual/open/comparison.
  - >90% of numeric-intent queries resolved tool-first (with auditable traces).
- Operability:
  - explicit SLOs + error budgets for quality and latency, reviewed weekly.

## 3) Prioritized Roadmap

## P0: Trust and Correctness (immediate)

1. Deterministic numeric-intent routing and tool-first response policy
- Customer outcome: fewer “obvious numeric mistakes,” higher trust for daily workflow questions.
- Plan:
  - strengthen numeric-intent classifier and hard-route to finance tools first.
  - require explicit fallback reason when switching to RAG.
  - add per-answer tool-coverage metadata (what tool answered which claim).
- KPI:
  - numeric-intent tool-use rate, numeric accuracy, factual correctness fail.

2. Claim-level grounding checks before final answer
- Customer outcome: fewer unsupported key claims in long-form answers.
- Plan:
  - lightweight post-draft verifier over material claims only (entities, periods, key numbers, directional statements).
  - fail closed to “insufficient evidence” when key claim support is missing.
- KPI:
  - open-ended faithfulness fail, manual-audit precision of judge fails.

3. Judge reliability hardening
- Customer outcome: customers and internal teams can trust quality dashboards.
- Plan:
  - keep dev/test split and manual-labeled reliability set.
  - add bootstrap confidence intervals to all headline fail rates.
  - periodic adjudication of disagreement buckets.
- KPI:
  - fail precision/recall against human labels, confidence interval width.

## P1: Latency and Throughput (near-term)

4. Prompt-prefix stabilization + prompt caching strategy
- Customer outcome: faster answers and lower cost for repeated analysis flows.
- Plan:
  - maximize static prompt prefix and move dynamic context later.
  - measure cached-token share and latency deltas by query family.
- KPI:
  - cached_tokens ratio, p95 latency, token cost per answer.

5. Retrieval budget scheduler (adaptive k, not fixed k)
- Customer outcome: “simple questions are fast, complex questions are deep.”
- Plan:
  - adaptive `top_k_retrieve/top_k_rerank` based on intent complexity and ambiguity.
  - enforce latency budgets with graceful degradation policy.
- KPI:
  - latency/quality frontier area (Pareto improvements), timeout rate.

6. Query plan parallelism and speculative execution
- Customer outcome: lower wall-clock time without quality regression.
- Plan:
  - parallelize independent tool calls and retrieval branches.
  - speculative tool execution for high-probability routes, cancel on mismatch.
- KPI:
  - wall-clock reduction at matched quality.

## P2: Coverage and Product Depth (mid-term)

7. “Explain-your-numbers” answer mode
- Customer outcome: investment teams can audit and reuse answers in memos quickly.
- Plan:
  - answer format with explicit “source -> transformation -> final number” blocks.
  - one-click export to markdown table/citation appendix.
- KPI:
  - helpfulness score, user correction rate.

8. Comparative analysis pack for multi-ticker workflows
- Customer outcome: faster prep for committee decks and IC discussions.
- Plan:
  - structured multi-company summaries with normalized metric frames.
  - visible missing-data flags (avoid false confidence).
- KPI:
  - comparison fail/helpfulness fail, user-reported decision readiness.

9. Domain pack expansion (sector templates + custom lenses)
- Customer outcome: analysts can ask sector-specific questions with less prompt engineering.
- Plan:
  - sector-aware prompt templates (semis, industrials, software, consumer).
  - customer-defined “analysis lenses” saved per workspace.
- KPI:
  - first-try answer acceptance rate by sector.

## P3: Enterprise and Governance (mid/long-term)

10. SLO-driven quality operations
- Customer outcome: dependable production behavior with explicit reliability promises.
- Plan:
  - define latency and quality SLIs/SLOs and error budget policies.
  - release gates keyed to eval regressions and confidence intervals.
- KPI:
  - SLO attainment, rollback frequency, incident MTTR.

11. AI risk and compliance controls
- Customer outcome: easier procurement and enterprise trust.
- Plan:
  - map controls to NIST AI RMF categories.
  - preserve full lineage: prompt/version/data profile/eval run IDs.
- KPI:
  - control coverage, audit readiness time.

12. Data-source operational hardening for SEC ecosystems
- Customer outcome: fewer ingestion disruptions and better freshness predictability.
- Plan:
  - enforce SEC-compliant request shaping, adaptive backoff, and queueing.
  - explicit staleness indicators in UI when source refresh lags.
- KPI:
  - ingestion success rate, freshness SLA attainment.

## 4) Technical Bets Worth Prototyping

- Adaptive retrieval-control patterns inspired by Self-RAG/CRAG-style selective retrieval and retrieval-quality correction.
- Long-context robustness mitigations against “lost-in-the-middle” behavior via improved context ordering/diversification and answer-time evidence prioritization.
- Retrieval infra tuning using pgvector index and scan controls to move the latency/recall frontier.

These should be treated as hypothesis-driven experiments with clear guardrails and rollback criteria.

## 5) Suggested Execution Sequence

1. P0.1 + P0.2 + P1.4 as a trust/latency combo sprint.
2. P0.3 as quality-dashboard hardening gate.
3. P1.5 + P1.6 for frontier expansion.
4. P2 comparative and explainability features.
5. P3 operationalization and governance packaging.

## References

- OpenAI Cookbook: Eval-driven system design (production workflow)
  - https://cookbook.openai.com/examples/partners/eval_driven_system_design/receipt_inspection
- OpenAI API docs: Using tools
  - https://platform.openai.com/docs/guides/tools/file-search
- OpenAI API docs: Prompt caching best practices
  - https://platform.openai.com/docs/guides/prompt-caching/best-practices
- OpenAI API docs: Latency optimization
  - https://platform.openai.com/docs/guides/latency-optimization
- Liu et al., “Lost in the Middle: How Language Models Use Long Contexts” (TACL/arXiv)
  - https://arxiv.org/abs/2307.03172
- Asai et al., “Self-RAG” (arXiv)
  - https://arxiv.org/abs/2310.11511
- Yan et al., “Corrective Retrieval Augmented Generation (CRAG)” (arXiv)
  - https://arxiv.org/abs/2401.15884
- pgvector official repository and index tuning notes
  - https://github.com/pgvector/pgvector
- Google SRE book: Service Level Objectives
  - https://sre.google/sre-book/service-level-objectives/
- NIST AI RMF 1.0
  - https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-ai-rmf-10
- SEC EDGAR rate control notice (operational constraint)
  - https://www.sec.gov/filergroup/announcements-old/new-rate-control-limits
