# Benchmark Report

_Last updated: 2026-02-18_

## Scope
This report consolidates the latest latency/accuracy benchmarking runs for the financial RAG pipeline.

Benchmark protocol for this report:
- Query sets: `single100` + `multi60`
- Generation: deploy-matched `normal` mode unless explicitly varied
- Tools: enabled
- Refine: disabled (`--enable-refine 0`)
- Concurrency: `12` threads
- Query timeout/retries: `350s`, `1` retry
- Judge: `12` workers, `judge_context_chars=80000`, timeout `350s`, retries `1`

Primary artifacts:
- `eval/results_revamp/latency_accuracy_frontier_20260218/frontier_manifest.csv`
- `eval/results_revamp/latency_accuracy_frontier_20260218/latency_accuracy_frontier_metrics.csv`
- `eval/results_revamp/chunk_size_study_v2_expanded80k/chunk_size_metrics_expanded80k.csv`
- `eval/results_revamp/judge_stability_single100_baseline_20260218/judge_stability_replicate_metrics.json`

## Experiment Catalog
This is the exact frontier experiment set that was executed.

| exp_id | axis | what changed | why this was run |
|---|---|---|---|
| `baseline_normal` | `baseline` | `normal` preset defaults (`40/25`, rerank on) | control run for all comparisons |
| `effort_low` | `answering_effort` | answering effort `low` | test lower synthesis effort latency/quality tradeoff |
| `effort_high` | `answering_effort` | answering effort `high` | test higher synthesis effort quality gain vs latency cost |
| `retrieve_low_30_18` | `retrieval_depth` | `top_k_retrieve=30`, `top_k_rerank=18` | test shallower retrieval budget |
| `retrieve_high_60_35` | `retrieval_depth` | `top_k_retrieve=60`, `top_k_rerank=35` | test deeper retrieval budget |
| `temperature_0` | `generation_behavior` | draft temperature `0.0` | test deterministic decoding behavior |
| `tight_tokens_32k_16k` | `generation_budget` | draft/final max tokens reduced to `32768/16384` | test tighter generation budget |
| `rerank_off_40_25` | `rerank` | reranking disabled at normal retrieval depth | isolate reranker contribution |
| `mode_quick` | `preset_mode` | quick preset (legacy run) | early quick-mode baseline |
| `mode_thinking` | `preset_mode` | thinking preset | high-effort preset tradeoff point |
| `mode_quick_true` | `preset_mode` | quick preset with corrected `--mode quick` wiring | corrected quick-mode result |
| `strategy_baseline_flags_explicit` | `retrieval_strategy` | explicit strategy flags `mmr=0, adaptive=1` | **control for strategy ablation**: same intended default strategy but explicit toggles to avoid implicit-default ambiguity |
| `strategy_mmr_on` | `retrieval_strategy` | `mmr=1, adaptive=1` | isolate effect of enabling MMR while keeping adaptive budget on |
| `strategy_adaptive_off` | `retrieval_strategy` | `mmr=0, adaptive=0` | isolate effect of disabling adaptive budget |
| `strategy_mmr_on_adaptive_off` | `retrieval_strategy` | `mmr=1, adaptive=0` | test MMR without adaptive budget |
| `narrative_full_guardrails` | `narrative_retrieval` | `query_expansion=1`, `aspect_coverage=1` | test full narrative retrieval guardrails |
| `narrative_minimal_guardrails` | `narrative_retrieval` | `query_expansion=0`, `aspect_coverage=0` | test minimal narrative overhead baseline |

## Results Summary Table
All frontier runs with core metrics.

| exp_id | axis | setting | qps | p95_ms | factual_fail | open_faith_fail | comparison_fail |
|---|---|---|---:|---:|---:|---:|---:|
| `baseline_normal` | `baseline` | `normal_default` | 0.1408 | 153175.6 | 0.0857 | 0.1667 | 0.0167 |
| `effort_low` | `answering_effort` | `low` | 0.1416 | 154107.2 | 0.0571 | 0.0000 | 0.0333 |
| `effort_high` | `answering_effort` | `high` | 0.1390 | 157353.1 | 0.0286 | 0.0333 | 0.0167 |
| `retrieve_low_30_18` | `retrieval_depth` | `top_k_retrieve=30,top_k_rerank=18` | 0.1477 | 160977.7 | 0.0571 | 0.1000 | 0.0167 |
| `retrieve_high_60_35` | `retrieval_depth` | `top_k_retrieve=60,top_k_rerank=35` | 0.1276 | 172178.0 | 0.1714 | 0.0667 | 0.0167 |
| `temperature_0` | `generation_behavior` | `draft_temperature=0.0` | 0.1333 | 165182.1 | 0.0286 | 0.1333 | 0.0167 |
| `tight_tokens_32k_16k` | `generation_budget` | `draft_max_tokens=32768,final_max_tokens=16384` | 0.1077 | 162894.1 | 0.0857 | 0.0667 | 0.0333 |
| `rerank_off_40_25` | `rerank` | `enable_rerank=0` | 0.1269 | 188579.3 | 0.0571 | 0.0667 | 0.0167 |
| `mode_quick` | `preset_mode` | `quick` | 0.1399 | 159210.6 | 0.0286 | 0.1000 | 0.0167 |
| `mode_thinking` | `preset_mode` | `thinking` | 0.0776 | 294960.7 | 0.1143 | 0.0667 | 0.0167 |
| `mode_quick_true` | `preset_mode` | `quick` | 0.2392 | 98157.3 | 0.0571 | 0.0333 | 0.0500 |
| `strategy_baseline_flags_explicit` | `retrieval_strategy` | `mmr=0,adaptive=1` | 0.1396 | 154830.0 | 0.1429 | 0.0000 | 0.0167 |
| `strategy_mmr_on` | `retrieval_strategy` | `mmr=1,adaptive=1` | 0.1072 | 158371.7 | 0.0000 | 0.0333 | 0.0167 |
| `strategy_adaptive_off` | `retrieval_strategy` | `mmr=0,adaptive=0` | 0.1213 | 178635.1 | 0.0286 | 0.1000 | 0.0333 |
| `strategy_mmr_on_adaptive_off` | `retrieval_strategy` | `mmr=1,adaptive=0` | 0.1169 | 161613.1 | 0.0286 | 0.1000 | 0.0167 |
| `narrative_full_guardrails` | `narrative_retrieval` | `query_expansion=1,aspect_coverage=1` | 0.1185 | 159802.9 | 0.0286 | 0.0667 | 0.0167 |
| `narrative_minimal_guardrails` | `narrative_retrieval` | `query_expansion=0,aspect_coverage=0` | 0.1366 | 163159.5 | 0.0286 | 0.1000 | 0.0167 |

## Topline Visuals

### Latency vs Open-Ended Faithfulness
![Frontier Scatter](agent_logs/reports/benchmark_figures_20260218/frontier_open_faithfulness_scatter.png)

### Throughput Ranking (Readable)
![Throughput Ranking](agent_logs/reports/benchmark_figures_20260218/frontier_throughput_ranked.png)

## Retrieval Strategy Ablation
Toggle axis:
- `FINRAG_ENABLE_MMR_DIVERSITY`
- `FINRAG_ENABLE_ADAPTIVE_RETRIEVAL_BUDGET`

| setting | qps | p95_ms | factual_fail | open_faith_fail | comparison_fail |
|---|---:|---:|---:|---:|---:|
| `mmr=0,adaptive=1` | 0.1396 | 154830.0 | 0.1429 | 0.0000 | 0.0167 |
| `mmr=1,adaptive=1` | 0.1072 | 158371.7 | 0.0000 | 0.0333 | 0.0167 |
| `mmr=0,adaptive=0` | 0.1213 | 178635.1 | 0.0286 | 0.1000 | 0.0333 |
| `mmr=1,adaptive=0` | 0.1169 | 161613.1 | 0.0286 | 0.1000 | 0.0167 |

Interpretation:
- `strategy_mmr_on` improved factual correctness on this dataset, with throughput cost.
- Disabling adaptive budget regressed open-faithfulness in this sweep.
- `strategy_baseline_flags_explicit` is a strict strategy-control run, not a new algorithm.

![Retrieval Strategy Tradeoffs](agent_logs/reports/benchmark_figures_20260218/retrieval_strategy_tradeoffs.png)

## Narrative Guardrail Ablation
Toggle axis:
- `FINRAG_ENABLE_NARRATIVE_QUERY_EXPANSION`
- `FINRAG_ENABLE_NARRATIVE_ASPECT_COVERAGE`

| setting | qps | p95_ms | factual_fail | open_faith_fail | comparison_fail |
|---|---:|---:|---:|---:|---:|
| `query_expansion=1,aspect_coverage=1` | 0.1185 | 159802.9 | 0.0286 | 0.0667 | 0.0167 |
| `query_expansion=0,aspect_coverage=0` | 0.1366 | 163159.5 | 0.0286 | 0.1000 | 0.0167 |

Interpretation:
- Full narrative guardrails improved open-ended faithfulness.
- Minimal guardrails improved throughput but weakened narrative faithfulness.

![Narrative Guardrails Tradeoffs](agent_logs/reports/benchmark_figures_20260218/narrative_guardrails_tradeoffs.png)

## Chunk Size Ablation (Judge Context 80k)

| chunk_size | overlap | qps | p95_ms | factual_fail | open_faith_fail | comparison_fail |
|---:|---:|---:|---:|---:|---:|---:|
| 256 | 32 | 0.1321 | 180216.6 | 0.0857 | 0.0000 | 0.0333 |
| 512 | 64 | 0.1385 | 162625.8 | 0.0571 | 0.0667 | 0.0167 |
| 1024 | 128 | 0.1376 | 158374.3 | 0.1143 | 0.1000 | 0.0333 |
| 2048 | 256 | 0.1360 | 152962.3 | 0.0857 | 0.2000 | 0.0167 |

![Chunk Size Tradeoffs](agent_logs/reports/benchmark_figures_20260218/chunk_size_tradeoffs.png)

## Explaining Surprising Results

### Why did the tight token budget reduce throughput?
- The drop was mostly a long-tail retry artifact, not a broad decoding-speed improvement/regression signal.
- `tight_tokens_32k_16k` had `1` retried query in `single100` (`query_attempts=2`) that took `388,467ms`; baseline had `0` retries.
- The same query in baseline took `44,097ms`, so that one outlier added most of the wall-clock delta.
- Single-run wall time moved from `439,551ms` (baseline) to `779,984ms` (tight), even though average per-query latency only moved from `49,616ms` to `52,348ms`.
- Counterfactual check: replacing only that outlier with the run median recovers throughput from `0.1077` to `0.1395 qps` (near baseline `0.1408 qps`).

### Why can deeper retrieval worsen faithfulness?
- Important nuance: in the explicit depth sweep, open-ended faithfulness did **not** worsen (`0.1667` baseline vs `0.0667` at `60/35`); what worsened strongly was factual correctness (`0.0857` -> `0.1714`) and latency.
- Mechanism observed in traces: depth `60/35` increased reranked context volume from about `30.8k` chars/query to `44.9k` chars/query (top chunks), and top chunk count from `21.0` to `29.7`.
- Additional factual fails were mostly period/column confusion in financial tables (for example 3-month vs 9-month values, attribution columns, fiscal-period mismatches), consistent with context dilution/competition.
- Related retrieval-strategy runs also show the same pattern risk: settings that reduce targeting quality can increase open-faithfulness fails (for example `adaptive=0` runs at `0.1000`).

### Why is chunk size 512 the best operating point here?
- `512` is the best balance between retrieval precision and context completeness in this benchmark.
- `256` fragments evidence too much for this pipeline configuration and had tail instability (`2` retries, with outliers at `503,718ms` and `397,521ms`), which hurt throughput (`0.1321 qps`).
- `1024` and `2048` increase per-query injected context size materially (mean top-chunk text: `37.6k` and `42.9k` chars vs `30.8k` at `512`), which raises context mixing and weakens grounding selectivity.
- That aligns with observed quality: open-faithfulness fail rises from `0.0667` (`512`) to `0.1000` (`1024`) and `0.2000` (`2048`), while `512` also has the best factual-fail rate (`0.0571`) among chunk sizes.

## Judge Stability (Fixed Generations)
6 independent rescoring passes on the same single100 baseline generations.

| metric | mean | stddev | min | max |
|---|---:|---:|---:|---:|
| factual_fail | 0.0619 | 0.0106 | 0.0571 | 0.0857 |
| factual_help_fail | 0.0190 | 0.0135 | 0.0000 | 0.0286 |
| open_faith_fail | 0.1000 | 0.0272 | 0.0667 | 0.1333 |
| open_help_fail | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| distractor_focus_fail | 0.0667 | 0.0000 | 0.0667 | 0.0667 |

Implication:
- open-ended faithfulness has a material judge-variance band; small deltas must be interpreted cautiously.

![Judge Variance](agent_logs/reports/benchmark_figures_20260218/judge_variance_replicates.png)

## Reproducibility Scripts
- `agent_logs/scripts/eval/20260218_060700_collect_latency_accuracy_frontier.py`
- `agent_logs/scripts/eval/20260218_114300_extend_latency_accuracy_frontier_mmr_adaptive.sh`
- `agent_logs/scripts/eval/20260218_115700_extend_latency_accuracy_frontier_narrative_flags.sh`
- `agent_logs/scripts/eval/20260218_113300_judge_stability_rescore_single100_baseline.sh`
- `agent_logs/scripts/eval/20260218_154300_build_benchmark_report_figures.py`

## Golden Defaults (Recommended Moving Forward)

This is the recommended default profile for deployed usage and future eval loops.

### Retrieval + index
- chunking: `512` max tokens, `64` overlap.
- sparse retrieval: `bm25`.
- retrieval mode: full chunk text (deploy-matched).

### Answering runtime
- mode: `normal`.
- answering effort: `high`.
- preset-resolved controls:
  - `top_k_retrieve=40`
  - `top_k_rerank=25`
  - `draft_max_tokens=65536`
  - `final_max_tokens=32768`
  - `brief_max_tokens=8000`
  - `enable_rerank=true`
  - `enable_refine=false`
- retrieval strategy toggles:
  - `FINRAG_ENABLE_NARRATIVE_QUERY_EXPANSION=0` (default off)
  - `FINRAG_ENABLE_NARRATIVE_ASPECT_COVERAGE=1`
  - `FINRAG_ENABLE_ADAPTIVE_RETRIEVAL_BUDGET=1`
  - `FINRAG_ENABLE_MMR_DIVERSITY=0`

### Eval harness defaults
- generation workers: `12` (thread backend).
- judge workers: `12`.
- generation timeout/retries: `350s`, `1` retry.
- judge context/timeout/retries: `80000`, `350s`, `1` retry.

### Why this profile
- `chunk=512` is the best measured latency/quality compromise in the rerun (`80k` judge context).
- `normal + high effort` gave the strongest overall quality trade-off in the frontier with near-baseline throughput.
- query expansion is disabled by default to avoid semantic drift away from the user’s original request.
- judge settings above are required for stable faithfulness behavior (per LOGBOOK + judge-variance analysis).
