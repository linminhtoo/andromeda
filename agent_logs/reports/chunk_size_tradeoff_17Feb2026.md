# Chunk Size Tradeoff Study (Single-Ticker, Eval-50)

Date: 2026-02-17

## Objective
Measure how chunk size affects latency and eval quality under deploy-matching retrieval/generation settings.

## Setup
- Query set: `eval/eval_queries_revamp_single_balanced_validated_tol05_20260216.jsonl` (n=50)
- Chunk sizes: 256, 512, 1024, 2048
- Overlap: 1/8 of chunk size (32, 64, 128, 256)
- Indexing:
  - dense model: `BAAI/bge-m3`
  - sparse method: `bm25`
  - contextualization: `none`
- Generation settings:
  - mode: `normal`
  - refine: `off`
  - eval concurrency: `12`
  - query timeout: `600s`
- Judge settings:
  - workers: `8`
  - `judge_context_chars=65000` (used for all 4 sizes for consistency)

## Runs
- 256: `eval/results_revamp/chunk_size_study/runs/eval_run.single_chunk256_normal_v13_eval50.20260217_031325`
- 512: `eval/results_revamp/chunk_size_study/runs/eval_run.single_chunk512_normal_v13_eval50.20260217_032206`
- 1024: `eval/results_revamp/chunk_size_study/runs/eval_run.single_chunk1024_normal_v13_eval50.20260217_033110`
- 2048: `eval/results_revamp/chunk_size_study/runs/eval_run.single_chunk2048_normal_v13_eval50_t600.20260217_034832`

Note: an earlier 2048 attempt with `query-timeout-s=240` produced a timeout artifact and was discarded.

## Results
Source: `eval/results_revamp/chunk_size_study/chunk_size_metrics.csv`

| chunk | qps | p50 ms | p95 ms | factual correctness fail | open faithfulness fail |
|---:|---:|---:|---:|---:|---:|
| 256 | 0.2004 | 48778.2 | 92565.3 | 0.0000 | 0.4667 |
| 512 | 0.1837 | 52777.2 | 115069.4 | 0.0000 | 0.3333 |
| 1024 | 0.1684 | 57122.9 | 121489.9 | 0.0500 | 0.5333 |
| 2048 | 0.1587 | 56494.0 | 132782.6 | 0.0000 | 0.4667 |

## Interpretation
- Throughput declines monotonically as chunk size increases.
- Faithfulness is best at `512` in this sweep (`0.3333` fail), with a moderate latency cost versus `256`.
- `1024` is strictly worse than `512` on both latency and faithfulness in this dataset.
- `2048` has the worst tail latency (`p95`) and no quality gain over `512`.

## Practical recommendation
- Use `512` as the primary chunk size candidate for next iterations.
- Keep `256` as the speed baseline.
- Avoid `1024+` unless retrieval changes materially (for example, MMR/diversity-aware reranking) and re-evaluation shows clear gains.

## Artifacts
- Manifest: `eval/results_revamp/chunk_size_study/run_manifest.csv`
- Metrics table/json/md: `eval/results_revamp/chunk_size_study/chunk_size_metrics.{csv,json,md}`
- Figure: `eval/results_revamp/chunk_size_study/chunk_size_tradeoff.png`
- Runner script: `agent_logs/20260217_014500_run_chunk_size_tradeoff_eval.sh`
- Collector script: `agent_logs/20260217_014500_collect_chunk_size_metrics.py`
