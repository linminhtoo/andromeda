# README_EVAL

This is the canonical runbook for reproducing and extending the current eval pipeline.

It reflects the latest preferred setup from `agent_logs/LOGBOOK.md` and the latest best-known runs on this branch.

## 1) Current Best-Practice Eval Configuration

### Retrieval/index settings (generation side)
- ingest profile / schema: `eval_revamp_combined_512_20260217`
- chunking: `max_tokens=512`, `overlap_tokens=64`
- retrieval context mode: `context=none` (no per-chunk LLM contextualization at index time)
- dense model: `BAAI/bge-m3`
- sparse method: `bm25`

Rationale: in the controlled sweep (`agent_logs/reports/chunk_size_tradeoff_17Feb2026.md`), `512` dominated `1024` on both latency and faithfulness in the tested setting.

### Answering hyperparameters (generation side)
- generation preset: `normal` (`src/andromeda/llm/generation_controls.py`)
- resolved values used in evaluated generations:
  - `top_k_retrieve=40`
  - `top_k_rerank=25`
  - `draft_max_tokens=65536`
  - `final_max_tokens=32768`
  - `enable_rerank=true`
  - `enable_refine=false`
- `answering_effort=high`
- `draft_temperature=0.1`
- retrieval toggles:
  - `FINRAG_ENABLE_NARRATIVE_QUERY_EXPANSION=0`
  - `FINRAG_ENABLE_NARRATIVE_ASPECT_COVERAGE=1`
  - `FINRAG_ENABLE_ADAPTIVE_RETRIEVAL_BUDGET=1`
  - `FINRAG_ENABLE_MMR_DIVERSITY=0`
- tools: enabled by default (no `--disable-finance-tools`)
- workers/backend: `concurrency=12`, `parallel_backend=thread`
- generation timeout/retry (recommended): `query_timeout_s=350`, `query_max_retries=1`

### Judge/scoring hyperparameters
- `judge_workers=12`
- `judge_context_chars=80000`
- `judge_timeout_s=350`
- `judge_max_retries=1`
- active faithfulness rubric: materiality-calibrated `faithfulness_v1` in `src/andromeda/eval/judges.py`

## 2) Current Metrics Snapshot

### Full single-ticker suite (100 queries, all non-comparison kinds)
Run:
- `eval/results_revamp/single/eval_run.single_ext_chunk512_v1_normal_tools12_norefine_eval100.20260217_043752/score_summary.json`

Metrics:
- factual:
  - `numeric_accuracy=0.60`
  - `factual_correctness_v1` fail rate: `0.0571`
  - factual `helpfulness_v1` fail rate: `0.0286`
- open-ended:
  - `faithfulness_v1` fail rate: `0.2667`
  - open-ended `helpfulness_v1` fail rate: `0.0`
- refusal:
  - `refusal_v1` fail rate: `0.0`
- distractor:
  - `focus_v1` fail rate: `0.0667`
  - distractor `helpfulness_v1` fail rate: `0.0`

### Multi-ticker comparison snapshot
Run:
- `eval/results_revamp/multi/eval_run.multi_holistic_normal_v2_tools8_norefine_calibrated.20260216_234717/score_summary.json`

Metrics:
- comparison `comparison_v1` fail rate: `0.0417`
- comparison `helpfulness_v1` fail rate: `0.0`

### Open-ended stress + judge-tuning snapshot
Generation baseline run (200 diverse open-ended):
- `eval/results_revamp/open/eval_run.open_diverse200_iter0_baseline_normal_tools12_norefine_qt350_jt350.20260218_002122/score_summary.json`
  - faithfulness fail: `0.215`
  - helpfulness fail: `0.01`

Judge-iteration run (fixed generations, materiality-calibrated prompt):
- `eval/results_revamp/judge_tuning/eval_run.open200_judge_iter3_materiality.20260218_010749/score_summary.json`
  - faithfulness fail: `0.08`
  - helpfulness fail: `0.015`

Interpretation: the large faithfulness delta in judge-only rescoring indicates prior over-strict false positives; judge reliability should be interpreted with manual-audit calibration, not raw fail-rate alone.

## 3) One-Pass Full Eval Suite

### Quick path (assets already prepared)
```bash
source .venv/bin/activate
bash scripts/run_full_eval_suite.sh
```

### Full rebuild + run (single command path)
```bash
source .venv/bin/activate
PREPARE_ASSETS=1 bash scripts/run_full_eval_suite.sh
```

What this executes:
- optional data/query prep via `scripts/prepare_eval_assets.sh`
- single suite generation + scoring
- multi comparison suite generation + scoring
- open-ended 200 stress generation + scoring
- writes a consolidated manifest:
  - `eval/results_revamp/full_suite/<run_group>.manifest.json`

Important path-resolution behavior:
- `scripts/run_full_eval_suite.sh` now resolves `DOC_INDEX_PATH` from `INGEST_PROFILE` by default.
- It intentionally ignores stale `.env` `FINRAG_DOC_INDEX_PATH` unless you explicitly pass `DOC_INDEX_PATH` (or `FINRAG_DOC_INDEX_PATH_OVERRIDE`).
- Use `ALLOW_EVAL_PROFILE_MISMATCH=1` only when you intentionally want query/profile mismatches.

## 4) Query Generation Lineage (Including Tolerance Filtering)

The current eval assets are generated with these scripts:
- profile/index build: `agent_logs/scripts/eval/20260217_042950_build_combined_profile_chunk512.sh`
- validated query generation: `agent_logs/scripts/eval/20260217_043020_generate_eval_set_combined512_validated_tol05.sh`
- subset builder: `agent_logs/scripts/eval/20260217_043130_build_eval100_subsets_combined512_tol05.sh`
- open-ended 200 pool: `agent_logs/scripts/eval/20260217_235950_generate_openended200_diverse_v1.sh`

Key factual-label settings:
- `--validate-factual-with-edgar`
- `--edgar-rel-tol 0.5`
- `--factual-candidate-multiplier 8`

Current subset compositions:
- single suite (`eval/eval_queries_combined512_single_balanced100_validated_tol05_20260217.jsonl`)
  - factual `35`, open_ended `30`, refusal `20`, distractor `15`
- multi suite (`eval/eval_queries_combined512_multi_comparison60_validated_tol05_20260217.jsonl`)
  - comparison `60`
- open stress (`eval/eval_queries_openended200_diverse_20260217_v1.jsonl`)
  - open_ended `200`

## 5) How To Read Metrics

- All judge metrics are fail rates (`0` is best).
- `factual_numeric_accuracy` is stricter numeric matching and should be read together with `factual_correctness_v1`.
- Open-ended `faithfulness_v1` is currently the hardest metric; treat it jointly with manual audit precision.
- Helpfulness is tracked independently (`helpfulness_v1`) across factual/open-ended/distractor/comparison and should not regress while optimizing faithfulness.

## 6) Cohesive Improvement Story (Hiring-Manager Version)

The eval pipeline was upgraded in four major steps:

1. Metric coverage and ground truth quality
- Added `helpfulness_v1` across eval kinds.
- Added Edgar-backed factual validation and tolerance-aware label generation.
- Standardized per-kind fail-rate reporting in `score_summary.json`.

2. Runtime realism and throughput
- Switched to tools-enabled holistic evaluation (not RAG-only ablations) for production match.
- Moved to thread-based parallelism for local vLLM constraints, with 12-worker generation/judging.
- Added timeout + retry controls for both generation and judging to handle local decode stalls.

3. Retrieval/generation quality frontier
- Ran chunk-size tradeoff study (256/512/1024/2048) and selected `512` as the best latency/faithfulness compromise.
- Iterated open-ended answering/routing prompts with fixed infrastructure, improving faithfulness from early high-failure regimes to the best open100 iteration (`0.18` fail).

4. Judge reliability discipline
- Added decision-level audit harness (`scripts/judge_reliability.py`) with manual labels and dev/test evaluation.
- Performed fail-case audits to separate judge errors from genuine model errors.
- Calibrated faithfulness rubric toward material errors to reduce false-positive fail calls while preserving key-error sensitivity.

Net result: the project now has a reproducible, end-to-end eval system with explicit data lineage, production-matched answering settings, and auditable judge calibration, instead of single-run ad hoc scoring.

## 7) Planner Characteristics Eval (New)

Goal: verify that the planner correctly assigns multi-label query characteristics (`comparison`, `market_data`, `financial_metrics`, `filing_narrative`, `period_scoped`, `simple_numeric`) before downstream answering.

### Ground-truth dataset
- Dataset file (manual labels, non-LLM-generated):
  - `eval/eval_queries_planner_characteristics_manual100_20260219.jsonl`
- Generator source:
  - `src/andromeda/eval/planner_dataset.py`
  - `scripts/make_planner_eval_set.py`

### One-command run (when vLLM is up)
```bash
source .venv/bin/activate
bash scripts/run_planner_eval_suite.sh
```

This command:
- creates the manual dataset if missing,
- runs planner-only inference (no answer generation),
- scores predictions and writes a review CSV + markdown report.

### Manual run path
```bash
source .venv/bin/activate
python -m scripts.run_planner_eval \
  --eval-queries eval/eval_queries_planner_characteristics_manual100_20260219.jsonl \
  --out-dir eval/results_planner \
  --run-name planner_characteristics_manual100 \
  --concurrency 12 \
  --query-timeout-s 350 \
  --query-max-retries 1

python -m scripts.score_planner_eval \
  --run-dir <planner_eval_run_dir>
```

### Planner eval artifacts
Per run directory (`planner_eval_run.*`):
- `eval_queries.jsonl`
- `planner_predictions.jsonl`
- `planner_prediction_summary.json`
- `planner_scores.jsonl`
- `planner_score_summary.json`
- `planner_score_summary.md`
- `planner_review.csv`

### Key metrics produced
- characteristic exact match rate
- expected-subset recall rate
- macro/micro precision, recall, F1
- per-characteristic TP/FP/FN/TN with precision/recall/F1
- action accuracy for labeled action rows (`refused`, `clarification_required`)
