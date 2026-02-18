#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"

source .venv/bin/activate
set -a
. ./.env
set +a

export HOME=/tmp

SOURCE_RUN="eval/results_revamp/latency_accuracy_frontier_20260218/runs/eval_run.single100_baseline_normal.20260218_054432"
OUT_ROOT="eval/results_revamp/judge_stability_single100_baseline_20260218"
RUNS_DIR="${OUT_ROOT}/runs"
mkdir -p "${RUNS_DIR}"

MANIFEST="${OUT_ROOT}/manifest.csv"
echo "replicate,run_dir" > "${MANIFEST}"

N_REPLICATES=6

for i in $(seq 1 "${N_REPLICATES}"); do
  run_dir="${RUNS_DIR}/single100_baseline_rescore_${i}"
  rm -rf "${run_dir}"
  cp -a "${SOURCE_RUN}" "${run_dir}"
  rm -f "${run_dir}/scores.jsonl" "${run_dir}/cases.jsonl" "${run_dir}/review.csv" "${run_dir}/score_summary.json"

  python -m scripts.score_eval \
    --run-dir "${run_dir}" \
    --judge-workers 12 \
    --judge-context-chars 80000 \
    --judge-timeout-s 350 \
    --judge-max-retries 1

  echo "${i},${run_dir}" >> "${MANIFEST}"
done

python - "${MANIFEST}" "${OUT_ROOT}" <<'PY'
from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

manifest_path = Path(__import__("sys").argv[1]).resolve()
out_root = Path(__import__("sys").argv[2]).resolve()
rows: list[dict[str, Any]] = []

for row in csv.DictReader(manifest_path.open()):
    run_dir = Path(row["run_dir"]).resolve()
    summary = json.loads((run_dir / "score_summary.json").read_text(encoding="utf-8"))
    metrics = {
        "replicate": int(row["replicate"]),
        "run_dir": str(run_dir),
        "factual_fail": float(summary.get("factual_judge_fail_rates", {}).get("factual_correctness_v1", summary.get("factual_judge_fail_rate", 0.0))),
        "factual_help_fail": float(summary.get("factual_judge_fail_rates", {}).get("helpfulness_v1", summary.get("factual_helpfulness_fail_rate", 0.0))),
        "open_faith_fail": float(summary.get("open_ended_judge_fail_rates", {}).get("faithfulness_v1", summary.get("open_ended_judge_fail_rate", 0.0))),
        "open_help_fail": float(summary.get("open_ended_judge_fail_rates", {}).get("helpfulness_v1", summary.get("open_ended_helpfulness_fail_rate", 0.0))),
        "distractor_focus_fail": float(summary.get("distractor_judge_fail_rates", {}).get("focus_v1", summary.get("distractor_judge_fail_rate", 0.0))),
    }
    rows.append(metrics)

if not rows:
    raise SystemExit("No rows in manifest")

csv_path = out_root / "judge_stability_replicate_metrics.csv"
json_path = out_root / "judge_stability_replicate_metrics.json"
md_path = out_root / "judge_stability_replicate_metrics.md"

with csv_path.open("w", encoding="utf-8", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)

json_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")

metric_keys = ["factual_fail", "factual_help_fail", "open_faith_fail", "open_help_fail", "distractor_focus_fail"]
lines = ["# Judge Stability Rescore (Single100 Baseline)", "", f"- source run: `{Path(rows[0]['run_dir']).parent.parent / 'eval_run.single100_baseline_normal.20260218_054432'}`", ""]
lines.append("| metric | mean | stddev | min | max |")
lines.append("|---|---:|---:|---:|---:|")
for key in metric_keys:
    values = [float(r[key]) for r in rows]
    lines.append(
        f"| {key} | {mean(values):.4f} | {pstdev(values):.4f} | {min(values):.4f} | {max(values):.4f} |"
    )

lines.append("")
lines.append("## Replicates")
lines.append("")
lines.append("| replicate | factual_fail | factual_help_fail | open_faith_fail | open_help_fail | distractor_focus_fail |")
lines.append("|---:|---:|---:|---:|---:|---:|")
for row in sorted(rows, key=lambda item: int(item["replicate"])):
    lines.append(
        "| {replicate} | {factual_fail:.4f} | {factual_help_fail:.4f} | {open_faith_fail:.4f} | {open_help_fail:.4f} | {distractor_focus_fail:.4f} |".format(
            **row
        )
    )

md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"Wrote: {csv_path}")
print(f"Wrote: {json_path}")
print(f"Wrote: {md_path}")
PY

echo "Wrote manifest: ${MANIFEST}"
