# README_EVAL

This document explains how to reproduce the best single-ticker eval result from this project:

- Target run: `single_holistic_normal_v13_tools8_norefine_deploymatch_rescore_harness_judgev2`
- Target score file:
  - `eval/results_revamp/single/eval_run.single_holistic_normal_v13_tools8_norefine_deploymatch_rescore_harness_judgev2.20260216_231430/score_summary.json`
- Target headline metrics:
  - `factual_correctness_v1` fail rate: `0.05`
  - `open_ended faithfulness_v1` fail rate: `0.2666666667`

The reproduction path has 3 phases:

1. Build/index data profile
2. Generate/validate/filter eval queries
3. Run `v13` generation and score with `judgev2`

---

## 0) Prerequisites

From repo root:

```bash
source .venv/bin/activate
set -a; . ./.env; set +a
```

Assumed services up:

- Postgres
- vLLM chat endpoint (`OPENAI_CHAT_BASE_URL`)
- embedding endpoint (`OPENAI_EMBED_BASE_URL`)

Recommended env for sandboxed Edgar cache:

```bash
export HOME=/tmp
```

---

## 1) Build/index the eval profile

If you already have profile `eval_revamp_20260216` built and indexed, you can skip to Section 2.

### 1A. Full rebuild (download -> markdown -> chunk -> index)

Script used:

- `agent_logs/20260216_153446_rebuild_eval_profile.sh`

Run:

```bash
bash agent_logs/20260216_153446_rebuild_eval_profile.sh
```

Notable settings in this rebuild:

- tickers: `AMD NVDA INTC MU GOOGL AAPL MSFT AMZN META TSLA`
- `--year-cutoff 2025`
- chunking: `markdown_table_preserving`, `max_tokens=1024`, `overlap=128`
- index build uses:
  - `--postgres-schema eval_revamp_20260216`
  - `--context none`
  - `--sparse-search-method bm25`

### 1B. Index-only rebuild (if corpus files already exist)

Script used:

- `agent_logs/20260216_153752_rebuild_eval_index_only.sh`

Run:

```bash
bash agent_logs/20260216_153752_rebuild_eval_index_only.sh
```

---

## 2) Generate and filter eval queries (including tolerance filtering)

This is the part you asked about: yes, factual queries were filtered/annotated using Edgar validation and tolerance.

### 2A. Initial raw query generation (pre-validation)

Script:

- `agent_logs/20260216_153955_generate_eval_set_revamp.sh`

Output:

- `eval/eval_queries_revamp_20260216.jsonl`

### 2B. Edgar tolerance sweep (diagnostic)

Script:

- `agent_logs/20260216_164925_edgar_validation_tolerance_sweep.sh`

Purpose:

- measure how many factual candidates become `matched` as `--edgar-rel-tol` increases.

Observed sweep points included: `0.15, 0.20, 0.25, 0.30, 0.40, 0.50`.

### 2C. Build validated eval set at tolerance `0.5`

Script:

- `agent_logs/20260216_165030_generate_eval_set_validated_tol05_v3.sh`

Run:

```bash
bash agent_logs/20260216_165030_generate_eval_set_validated_tol05_v3.sh
```

This produces:

- `eval/eval_queries_revamp_validated_tol05_20260216.jsonl`

Expected distribution:

- total: `359`
- kind counts:
  - factual: `211`
  - open_ended: `60`
  - refusal: `24`
  - distractor: `24`
  - comparison: `40`
- factual Edgar validation statuses:
  - `matched: 24`
  - `mismatched: 52`
  - `skipped_unsupported_metric: 135`

### 2D. Build balanced single-ticker subset used by v13

Script:

- `agent_logs/20260216_165235_build_eval_subsets_from_validated_tol05_v1.sh`

Run:

```bash
bash agent_logs/20260216_165235_build_eval_subsets_from_validated_tol05_v1.sh
```

This creates:

- `eval/eval_queries_revamp_single_balanced_validated_tol05_20260216.jsonl`
- `eval/eval_queries_revamp_multi_comparison_validated_tol05_20260216.jsonl`

Single subset composition (used for v13):

- `factual=20`, `open_ended=15`, `refusal=8`, `distractor=7`
- factual rows are matched-only in this subset (`20/20 matched`).

---

## 3) Run v13 generation and baseline scoring

Script:

- `agent_logs/20260216_224650_eval_single_holistic_normal_v13_tools8_norefine_deploymatch.sh`

Run:

```bash
bash agent_logs/20260216_224650_eval_single_holistic_normal_v13_tools8_norefine_deploymatch.sh
```

This uses:

- eval queries: `eval/eval_queries_revamp_single_balanced_validated_tol05_20260216.jsonl`
- mode: `normal`
- refine: off
- workers: `concurrency=8`, `parallel-backend=thread`
- timeout: `240s`
- finance tools: enabled (no `--disable-finance-tools`)
- judge scoring context chars: `65000`

Reference generated run:

- `eval/results_revamp/single/eval_run.single_holistic_normal_v13_tools8_norefine_deploymatch.20260216_224314`

Reference score summary for this base v13 run:

- `factual_correctness_v1` fail: `0.25`
- `open_ended faithfulness_v1` fail: `0.5333333333`

---

## 4) Re-score v13 with harness + factual judge v2

Script:

- `agent_logs/20260216_232620_rescore_v13_harness_plus_factual_prompt_v2.sh`

Run:

```bash
bash agent_logs/20260216_232620_rescore_v13_harness_plus_factual_prompt_v2.sh
```

This copies v13 generations and re-scores with:

- `judge-workers=6`
- `judge-context-chars=80000`
- factual judge v2 wording (evidence/context wins if `Expected` conflicts)

Historical reference run:

- `eval/results_revamp/single/eval_run.single_holistic_normal_v13_tools8_norefine_deploymatch_rescore_harness_judgev2.20260216_231430`

Target summary:

```json
{
  "factual_judge_fail_rates": {"factual_correctness_v1": 0.05, "helpfulness_v1": 0.0},
  "open_ended_judge_fail_rates": {"faithfulness_v1": 0.26666666666666666, "helpfulness_v1": 0.0}
}
```

---

## 5) Exact historical reproduction note (important)

Current code includes later judge-context compaction behavior. A direct rerun of Section 4 may drift slightly.

To exactly reproduce the historical `20260216_231430` summary, use the back-compat reproduction harness:

- `agent_logs/20260217_002500_reproduce_v13_judgev2_notrunc.sh`

Run:

```bash
bash agent_logs/20260217_002500_reproduce_v13_judgev2_notrunc.sh
```

What this does:

- reuses the exact v13 generations
- scores with `judge-context-chars=80000`
- forces no per-chunk context truncation in judge context assembly (back-compat behavior)

Verified exact-match run:

- `eval/results_revamp/single/eval_run.single_holistic_normal_v13_tools8_norefine_deploymatch_rescore_harness_judgev2_repro_notrunc.20260217_002146/score_summary.json`

This file is JSON-equal to:

- `eval/results_revamp/single/eval_run.single_holistic_normal_v13_tools8_norefine_deploymatch_rescore_harness_judgev2.20260216_231430/score_summary.json`

---

## 6) Quick verification commands

Check target summary:

```bash
jq '.' eval/results_revamp/single/eval_run.single_holistic_normal_v13_tools8_norefine_deploymatch_rescore_harness_judgev2.20260216_231430/score_summary.json
```

Check exact-match repro summary:

```bash
jq '.' eval/results_revamp/single/eval_run.single_holistic_normal_v13_tools8_norefine_deploymatch_rescore_harness_judgev2_repro_notrunc.20260217_002146/score_summary.json
```

Compare equality directly:

```bash
python3 - <<'PY'
import json
from pathlib import Path
p1=Path('eval/results_revamp/single/eval_run.single_holistic_normal_v13_tools8_norefine_deploymatch_rescore_harness_judgev2.20260216_231430/score_summary.json')
p2=Path('eval/results_revamp/single/eval_run.single_holistic_normal_v13_tools8_norefine_deploymatch_rescore_harness_judgev2_repro_notrunc.20260217_002146/score_summary.json')
print(json.loads(p1.read_text()) == json.loads(p2.read_text()))
PY
```

Expected output:

- `True`

