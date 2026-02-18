#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt


def load_manifest_rows(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
        if header is None:
            return rows

        for line_idx, raw_row in enumerate(reader, start=2):
            if not raw_row:
                continue
            if len(raw_row) < 6:
                raise ValueError(f"Malformed manifest row {line_idx}: expected at least 6 columns, got {len(raw_row)}")

            exp_id = raw_row[0].strip()
            axis = raw_row[1].strip()
            single_run_dir = raw_row[-2].strip()
            multi_run_dir = raw_row[-1].strip()

            middle = [value.strip() for value in raw_row[2:-2]]
            if len(middle) == 1:
                setting = middle[0]
                notes = ""
            elif len(middle) == 2:
                setting, notes = middle
            else:
                # Handle old manifests written without CSV quoting where commas in
                # "setting" were split into extra columns.
                setting = ",".join(middle[:-1])
                notes = middle[-1]

            rows.append(
                {
                    "exp_id": exp_id,
                    "axis": axis,
                    "setting": setting,
                    "notes": notes,
                    "single_run_dir": single_run_dir,
                    "multi_run_dir": multi_run_dir,
                }
            )
    return rows


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    sorted_vals = sorted(values)
    idx = (len(sorted_vals) - 1) * p
    lo = int(idx)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = idx - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac


def metric_from_map(summary: dict[str, Any], key: str, metric: str, fallback_key: str) -> float | None:
    values = summary.get(key)
    if isinstance(values, dict):
        value = values.get(metric)
        if value is not None:
            return float(value)
    fallback = summary.get(fallback_key)
    return float(fallback) if fallback is not None else None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect latency/accuracy frontier metrics from run manifest.")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out-dir", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest_path = Path(args.manifest).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    for row in load_manifest_rows(manifest_path):
        single_run_dir = Path(row["single_run_dir"]).expanduser().resolve()
        multi_run_dir = Path(row["multi_run_dir"]).expanduser().resolve()

        single_gen = load_json(single_run_dir / "generation_summary.json")
        multi_gen = load_json(multi_run_dir / "generation_summary.json")
        single_score = load_json(single_run_dir / "score_summary.json")
        multi_score = load_json(multi_run_dir / "score_summary.json")

        single_generation_rows = load_jsonl(single_run_dir / "generations.jsonl")
        multi_generation_rows = load_jsonl(multi_run_dir / "generations.jsonl")

        latencies_ms: list[float] = []
        for item in single_generation_rows + multi_generation_rows:
            timing = item.get("timing_ms")
            if not isinstance(timing, dict):
                continue
            total_ms = timing.get("total_ms")
            if total_ms is None:
                continue
            latencies_ms.append(float(total_ms))

        single_n_ok = int(single_gen.get("n_ok", 0) or 0)
        multi_n_ok = int(multi_gen.get("n_ok", 0) or 0)
        total_n_ok = single_n_ok + multi_n_ok

        single_wall_total_ms = float(single_gen.get("wall_total_ms", 0.0) or 0.0)
        multi_wall_total_ms = float(multi_gen.get("wall_total_ms", 0.0) or 0.0)
        total_wall_total_ms = single_wall_total_ms + multi_wall_total_ms
        throughput_qps = (total_n_ok / (total_wall_total_ms / 1000.0)) if total_wall_total_ms > 0 else 0.0

        out_row = {
            "exp_id": row["exp_id"],
            "axis": row["axis"],
            "setting": row["setting"],
            "notes": row["notes"],
            "single_run_dir": str(single_run_dir),
            "multi_run_dir": str(multi_run_dir),
            "total_n_ok": total_n_ok,
            "throughput_qps": throughput_qps,
            "latency_p50_ms": percentile(latencies_ms, 0.50),
            "latency_p95_ms": percentile(latencies_ms, 0.95),
            "factual_numeric_accuracy": float(single_score.get("factual_numeric_accuracy", 0.0) or 0.0),
            "factual_correctness_fail_rate": metric_from_map(
                single_score,
                key="factual_judge_fail_rates",
                metric="factual_correctness_v1",
                fallback_key="factual_judge_fail_rate",
            ),
            "factual_helpfulness_fail_rate": metric_from_map(
                single_score,
                key="factual_judge_fail_rates",
                metric="helpfulness_v1",
                fallback_key="factual_helpfulness_fail_rate",
            ),
            "open_ended_faithfulness_fail_rate": metric_from_map(
                single_score,
                key="open_ended_judge_fail_rates",
                metric="faithfulness_v1",
                fallback_key="open_ended_judge_fail_rate",
            ),
            "open_ended_helpfulness_fail_rate": metric_from_map(
                single_score,
                key="open_ended_judge_fail_rates",
                metric="helpfulness_v1",
                fallback_key="open_ended_helpfulness_fail_rate",
            ),
            "refusal_fail_rate": metric_from_map(
                single_score,
                key="refusal_judge_fail_rates",
                metric="refusal_v1",
                fallback_key="refusal_judge_fail_rate",
            ),
            "distractor_focus_fail_rate": metric_from_map(
                single_score,
                key="distractor_judge_fail_rates",
                metric="focus_v1",
                fallback_key="distractor_judge_fail_rate",
            ),
            "distractor_helpfulness_fail_rate": metric_from_map(
                single_score,
                key="distractor_judge_fail_rates",
                metric="helpfulness_v1",
                fallback_key="distractor_helpfulness_fail_rate",
            ),
            "comparison_fail_rate": metric_from_map(
                multi_score,
                key="comparison_judge_fail_rates",
                metric="comparison_v1",
                fallback_key="comparison_judge_fail_rate",
            ),
            "comparison_helpfulness_fail_rate": metric_from_map(
                multi_score,
                key="comparison_judge_fail_rates",
                metric="helpfulness_v1",
                fallback_key="comparison_helpfulness_fail_rate",
            ),
        }
        rows.append(out_row)

    if not rows:
        raise SystemExit("No rows loaded from manifest.")

    csv_path = out_dir / "latency_accuracy_frontier_metrics.csv"
    json_path = out_dir / "latency_accuracy_frontier_metrics.json"
    md_path = out_dir / "latency_accuracy_frontier_metrics.md"
    fig_path = out_dir / "latency_accuracy_frontier.png"

    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    json_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")

    fig, axes = plt.subplots(1, 2, figsize=(15, 5))

    by_axis: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_axis.setdefault(str(row["axis"]), []).append(row)

    markers = ["o", "s", "^", "D", "P", "X", "*"]
    for idx, (axis_name, axis_rows) in enumerate(sorted(by_axis.items(), key=lambda item: item[0])):
        marker = markers[idx % len(markers)]
        x_vals = [r["latency_p95_ms"] / 1000.0 for r in axis_rows]
        y_vals = [r["open_ended_faithfulness_fail_rate"] for r in axis_rows]
        axes[0].scatter(x_vals, y_vals, label=axis_name, marker=marker, s=90, alpha=0.85)
        for r, x, y in zip(axis_rows, x_vals, y_vals, strict=False):
            axes[0].annotate(str(r["exp_id"]), (x, y), fontsize=8, alpha=0.9)

    axes[0].set_title("p95 Latency vs Open Faithfulness Fail")
    axes[0].set_xlabel("p95 latency (s)")
    axes[0].set_ylabel("fail rate")
    axes[0].grid(alpha=0.3)
    axes[0].legend()

    labels = [str(r["exp_id"]) for r in rows]
    qps = [r["throughput_qps"] for r in rows]
    axes[1].bar(labels, qps)
    axes[1].set_title("Throughput by Experiment")
    axes[1].set_xlabel("experiment")
    axes[1].set_ylabel("qps")
    axes[1].tick_params(axis="x", rotation=45)
    axes[1].grid(alpha=0.3, axis="y")

    fig.tight_layout()
    fig.savefig(fig_path, dpi=160)
    plt.close(fig)

    lines: list[str] = []
    lines.append("# Latency vs Accuracy Frontier Metrics")
    lines.append("")
    lines.append(f"- source manifest: `{manifest_path}`")
    lines.append(f"- figure: `{fig_path}`")
    lines.append("")
    lines.append("| exp_id | axis | setting | qps | p95_ms | factual_fail | open_faith_fail | comparison_fail |")
    lines.append("|---|---|---|---:|---:|---:|---:|---:|")
    for row in rows:
        lines.append(
            "| {exp_id} | {axis} | {setting} | {throughput_qps:.4f} | {latency_p95_ms:.1f} | {factual_correctness_fail_rate:.4f} | {open_ended_faithfulness_fail_rate:.4f} | {comparison_fail_rate:.4f} |".format(
                **row
            )
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Wrote: {csv_path}")
    print(f"Wrote: {json_path}")
    print(f"Wrote: {md_path}")
    print(f"Wrote: {fig_path}")


if __name__ == "__main__":
    main()
