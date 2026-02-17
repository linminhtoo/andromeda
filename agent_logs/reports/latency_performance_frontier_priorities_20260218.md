# Latency-Performance Frontier Priorities (2026-02-18)

Objective: map controllable runtime knobs to quality/latency tradeoffs under deploy-matched settings.

## Prioritization rubric
- Customer impact (trust + workflow speed)
- Implementation complexity
- Experimental turnaround time
- Risk of overfitting to current eval data

## Ranked knobs

1. `answering_effort` (`low|medium|high`)
- Why high priority:
  - directly affects synthesis depth and multi-ticker behavior;
  - likely high leverage on latency without invasive changes.
- Risk:
  - can under-explain nuanced narrative questions at `low`.
- Selected for execution: **Yes**.

2. Retrieval depth (`top_k_retrieve`, `top_k_rerank`)
- Why high priority:
  - central recall/latency driver;
  - likely interacts strongly with faithfulness and comparison quality.
- Risk:
  - too-high depth can add noisy evidence and hurt focus.
- Selected for execution: **Yes**.

3. Generation budget (`draft_max_tokens`, `final_max_tokens`)
- Why high priority:
  - strong latency knob with clear operational cost implications.
- Risk:
  - truncation or reduced synthesis completeness.
- Selected for execution: **Yes**.

4. Draft temperature (`draft_temperature`)
- Why medium priority:
  - small latency impact, but may change determinism/helpfulness and factual drift.
- Risk:
  - low impact vs compute spent.
- Selected for execution: **Yes** (single targeted ablation).

5. Judge-time controls (`judge_workers`, timeout/retry)
- Why medium priority:
  - affects evaluation throughput and reliability, not product response latency directly.
- Selected for execution now: **No** (already stabilized at 12 workers, 80k context).

6. Query timeout/retry policy
- Why medium priority:
  - reduces tail failures and improves completion rates under local model instability.
- Selected for execution now: **No** (kept fixed for comparability).

7. Mode-level preset switching (`quick|normal|thinking`)
- Why lower immediate priority:
  - bundles many variables at once, harder to isolate causal effects.
- Selected for execution now: **No** (decomposed into more surgical knobs above).

## Executed set for this iteration
- Baseline (`normal_default`)
- Answering effort: `low`, `high`
- Retrieval depth: `30/18`, `60/35`
- Generation behavior: `draft_temperature=0.0`
- Generation budget: `draft=32768`, `final=16384`

Script:
- `agent_logs/scripts/eval/20260218_060600_run_latency_accuracy_frontier.sh`
