#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt


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
    parser = argparse.ArgumentParser(description="Collect expanded chunk-size ablation metrics.")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out-dir", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest_path = Path(args.manifest).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    with manifest_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            chunk_size = int(row["chunk_size"])
            overlap = int(row["overlap"])
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
                "chunk_size": chunk_size,
                "overlap": overlap,
                "schema": row["schema"],
                "single_run_dir": str(single_run_dir),
                "multi_run_dir": str(multi_run_dir),
                "total_n_ok": total_n_ok,
                "single_n_ok": single_n_ok,
                "multi_n_ok": multi_n_ok,
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

    rows.sort(key=lambda item: item["chunk_size"])

    if not rows:
        raise SystemExit("No rows loaded from manifest.")

    csv_path = out_dir / "chunk_size_metrics_expanded80k.csv"
    json_path = out_dir / "chunk_size_metrics_expanded80k.json"
    md_path = out_dir / "chunk_size_metrics_expanded80k.md"
    fig_path = out_dir / "chunk_size_tradeoff_expanded80k.png"

    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    json_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")

    x = [row["chunk_size"] for row in rows]
    qps = [row["throughput_qps"] for row in rows]
    latency_p95_s = [row["latency_p95_ms"] / 1000.0 for row in rows]
    faith = [row["open_ended_faithfulness_fail_rate"] for row in rows]
    factual = [row["factual_correctness_fail_rate"] for row in rows]
    comparison = [row["comparison_fail_rate"] for row in rows]

    fig, axes = plt.subplots(1, 3, figsize=(16, 4.5))
    axes[0].plot(x, qps, marker="o", linewidth=2)
    axes[0].set_title("Chunk Size vs Throughput (single+multi)")
    axes[0].set_xlabel("chunk_size")
    axes[0].set_ylabel("qps")
    axes[0].grid(alpha=0.3)

    axes[1].plot(x, latency_p95_s, marker="o", linewidth=2)
    axes[1].set_title("Chunk Size vs p95 Latency")
    axes[1].set_xlabel("chunk_size")
    axes[1].set_ylabel("seconds")
    axes[1].grid(alpha=0.3)

    axes[2].plot(x, faith, marker="o", linewidth=2, label="open faithfulness fail")
    axes[2].plot(x, factual, marker="s", linewidth=2, label="factual correctness fail")
    axes[2].plot(x, comparison, marker="^", linewidth=2, label="comparison fail")
    axes[2].set_title("Chunk Size vs Key Fail Rates")
    axes[2].set_xlabel("chunk_size")
    axes[2].set_ylabel("fail rate")
    axes[2].set_ylim(0.0, 1.0)
    axes[2].legend()
    axes[2].grid(alpha=0.3)

    fig.tight_layout()
    fig.savefig(fig_path, dpi=160)
    plt.close(fig)

    lines: list[str] = []
    lines.append("# Expanded Chunk Size Tradeoff Metrics (Judge Context 80k)")
    lines.append("")
    lines.append(f"- source manifest: `{manifest_path}`")
    lines.append(f"- figure: `{fig_path}`")
    lines.append("")
    lines.append("| chunk_size | overlap | qps | p50_ms | p95_ms | factual_fail | open_faith_fail | comparison_fail |")
    lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|")
    for row in rows:
        lines.append(
            "| {chunk_size} | {overlap} | {throughput_qps:.4f} | {latency_p50_ms:.1f} | {latency_p95_ms:.1f} | {factual_correctness_fail_rate:.4f} | {open_ended_faithfulness_fail_rate:.4f} | {comparison_fail_rate:.4f} |".format(
                **row
            )
        )

    best_qps = max(rows, key=lambda item: item["throughput_qps"])
    best_faith = min(rows, key=lambda item: item["open_ended_faithfulness_fail_rate"])

    lines.append("")
    lines.append("## Highlights")
    lines.append(f"- Best throughput: chunk_size `{best_qps['chunk_size']}` ({best_qps['throughput_qps']:.4f} qps).")
    lines.append(
        f"- Best open-ended faithfulness fail: chunk_size `{best_faith['chunk_size']}` ({best_faith['open_ended_faithfulness_fail_rate']:.4f})."
    )
    lines.append("- Use full-table CSV/JSON for multi-metric decisions; single-metric ranking can be misleading.")

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Wrote: {csv_path}")
    print(f"Wrote: {json_path}")
    print(f"Wrote: {md_path}")
    print(f"Wrote: {fig_path}")


if __name__ == "__main__":
    main()
