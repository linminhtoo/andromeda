#!/usr/bin/env python3
"""Build readable benchmark report figures from existing eval artifacts."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt


def load_metrics_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def load_chunk_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def as_float(row: dict[str, str], key: str) -> float:
    return float(row[key])


def load_manifest_rows(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        _header = next(reader, None)
        for raw in reader:
            if not raw or len(raw) < 6:
                continue
            exp_id = raw[0].strip()
            axis = raw[1].strip()
            single_run_dir = raw[-2].strip()
            multi_run_dir = raw[-1].strip()
            middle = [value.strip() for value in raw[2:-2]]
            if len(middle) == 1:
                setting = middle[0]
                notes = ""
            elif len(middle) == 2:
                setting, notes = middle
            else:
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


def build_frontier_scatter(rows: list[dict[str, str]], out_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(11, 6.5))

    axis_colors = {
        "baseline": "#1f77b4",
        "answering_effort": "#ff7f0e",
        "retrieval_depth": "#2ca02c",
        "generation_behavior": "#d62728",
        "generation_budget": "#9467bd",
        "rerank": "#8c564b",
        "preset_mode": "#e377c2",
        "retrieval_strategy": "#17becf",
        "narrative_retrieval": "#bcbd22",
    }

    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault(row["axis"], []).append(row)

    for axis_name, axis_rows in sorted(grouped.items(), key=lambda item: item[0]):
        color = axis_colors.get(axis_name, "#333333")
        xs = [as_float(row, "latency_p95_ms") / 1000.0 for row in axis_rows]
        ys = [as_float(row, "open_ended_faithfulness_fail_rate") for row in axis_rows]
        ax.scatter(xs, ys, label=axis_name, s=95, alpha=0.9, color=color, edgecolors="black", linewidths=0.4)

    highlight_ids = {"baseline_normal", "mode_quick_true", "effort_low", "strategy_mmr_on", "narrative_full_guardrails"}
    for row in rows:
        if row["exp_id"] not in highlight_ids:
            continue
        x = as_float(row, "latency_p95_ms") / 1000.0
        y = as_float(row, "open_ended_faithfulness_fail_rate")
        ax.annotate(row["exp_id"], (x, y), fontsize=8, xytext=(5, 5), textcoords="offset points")

    ax.set_title("Latency vs Open-Ended Faithfulness Failure")
    ax.set_xlabel("p95 latency (seconds)")
    ax.set_ylabel("open-ended faithfulness fail rate")
    ax.grid(alpha=0.3)
    ax.legend(loc="upper right", fontsize=8, ncol=2)
    fig.tight_layout()
    fig.savefig(out_path, dpi=180)
    plt.close(fig)


def build_throughput_ranking(rows: list[dict[str, str]], out_path: Path) -> None:
    ranked = sorted(rows, key=lambda row: as_float(row, "throughput_qps"), reverse=True)
    labels = [row["exp_id"] for row in ranked]
    values = [as_float(row, "throughput_qps") for row in ranked]

    fig_h = max(6.0, 0.32 * len(labels))
    fig, ax = plt.subplots(figsize=(11, fig_h))

    y_positions = list(range(len(labels)))
    bars = ax.barh(y_positions, values, color="#1f77b4", edgecolor="black", linewidth=0.4)
    ax.set_yticks(y_positions)
    ax.set_yticklabels(labels)
    ax.invert_yaxis()
    ax.set_xlabel("throughput (qps)")
    ax.set_title("Throughput Ranking by Experiment")
    ax.grid(alpha=0.25, axis="x")

    for bar, value in zip(bars, values, strict=False):
        ax.text(bar.get_width() + 0.0015, bar.get_y() + (bar.get_height() / 2), f"{value:.3f}", va="center", fontsize=8)

    fig.tight_layout()
    fig.savefig(out_path, dpi=180)
    plt.close(fig)


def _add_bar_labels(ax: plt.Axes, bars: Any, y_offset: float = 0.004) -> None:
    for bar in bars:
        height = float(bar.get_height())
        ax.text(
            bar.get_x() + (bar.get_width() / 2),
            height + y_offset,
            f"{height:.3f}",
            ha="center",
            va="bottom",
            fontsize=8,
        )


def build_retrieval_strategy_tradeoff(rows: list[dict[str, str]], out_path: Path) -> None:
    subset = [row for row in rows if row["axis"] == "retrieval_strategy"]
    subset.sort(key=lambda row: row["exp_id"])

    labels = [row["setting"] for row in subset]
    qps = [as_float(row, "throughput_qps") for row in subset]
    factual_fail = [as_float(row, "factual_correctness_fail_rate") for row in subset]
    open_faith_fail = [as_float(row, "open_ended_faithfulness_fail_rate") for row in subset]
    comparison_fail = [as_float(row, "comparison_fail_rate") for row in subset]

    x = list(range(len(labels)))
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.5))

    bars = axes[0].bar(x, qps, color="#1f77b4", edgecolor="black", linewidth=0.4)
    axes[0].set_xticks(x)
    axes[0].set_xticklabels(labels, rotation=12, ha="right")
    axes[0].set_ylabel("qps")
    axes[0].set_title("Retrieval Strategy Throughput")
    axes[0].grid(alpha=0.25, axis="y")
    _add_bar_labels(axes[0], bars, y_offset=0.0018)

    width = 0.24
    left = [val - width for val in x]
    middle = x
    right = [val + width for val in x]

    factual_bars = axes[1].bar(
        left, factual_fail, width=width, color="#d62728", edgecolor="black", linewidth=0.4, label="factual_fail"
    )
    open_bars = axes[1].bar(
        middle, open_faith_fail, width=width, color="#ff7f0e", edgecolor="black", linewidth=0.4, label="open_faith_fail"
    )
    comparison_bars = axes[1].bar(
        right, comparison_fail, width=width, color="#2ca02c", edgecolor="black", linewidth=0.4, label="comparison_fail"
    )

    axes[1].set_xticks(x)
    axes[1].set_xticklabels(labels, rotation=12, ha="right")
    axes[1].set_ylabel("fail rate")
    axes[1].set_ylim(0.0, max(factual_fail + open_faith_fail + comparison_fail) + 0.04)
    axes[1].set_title("Retrieval Strategy Failure Rates")
    axes[1].grid(alpha=0.25, axis="y")
    axes[1].legend()

    _add_bar_labels(axes[1], factual_bars)
    _add_bar_labels(axes[1], open_bars)
    _add_bar_labels(axes[1], comparison_bars)

    fig.tight_layout()
    fig.savefig(out_path, dpi=180)
    plt.close(fig)


def build_narrative_guardrails_tradeoff(rows: list[dict[str, str]], out_path: Path) -> None:
    subset = [row for row in rows if row["axis"] == "narrative_retrieval"]
    subset.sort(key=lambda row: row["exp_id"])

    labels = [row["setting"] for row in subset]
    qps = [as_float(row, "throughput_qps") for row in subset]
    open_faith_fail = [as_float(row, "open_ended_faithfulness_fail_rate") for row in subset]
    p95_s = [as_float(row, "latency_p95_ms") / 1000.0 for row in subset]

    x = list(range(len(labels)))

    fig, ax1 = plt.subplots(figsize=(9, 5))
    bars = ax1.bar(x, qps, color="#1f77b4", edgecolor="black", linewidth=0.4, label="qps")
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, rotation=12, ha="right")
    ax1.set_ylabel("qps", color="#1f77b4")
    ax1.tick_params(axis="y", labelcolor="#1f77b4")
    ax1.grid(alpha=0.25, axis="y")
    _add_bar_labels(ax1, bars, y_offset=0.002)

    ax2 = ax1.twinx()
    open_line = ax2.plot(x, open_faith_fail, color="#d62728", marker="o", label="open_faith_fail")
    p95_line = ax2.plot(x, p95_s, color="#2ca02c", marker="s", label="p95_seconds")
    ax2.set_ylabel("open_faith_fail / p95_seconds")

    ax1.set_title("Narrative Guardrails: Speed vs Faithfulness")

    lines_1, labels_1 = ax1.get_legend_handles_labels()
    lines_2, labels_2 = ax2.get_legend_handles_labels()
    ax2.legend(lines_1 + lines_2 + open_line + p95_line, labels_1 + labels_2, loc="upper left")

    fig.tight_layout()
    fig.savefig(out_path, dpi=180)
    plt.close(fig)


def build_chunk_tradeoff(chunk_rows: list[dict[str, str]], out_path: Path) -> None:
    chunk_rows.sort(key=lambda row: int(row["chunk_size"]))
    sizes = [int(row["chunk_size"]) for row in chunk_rows]
    qps = [float(row["throughput_qps"]) for row in chunk_rows]
    p95_s = [float(row["latency_p95_ms"]) / 1000.0 for row in chunk_rows]
    factual_fail = [float(row["factual_correctness_fail_rate"]) for row in chunk_rows]
    open_faith_fail = [float(row["open_ended_faithfulness_fail_rate"]) for row in chunk_rows]

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))

    axes[0].plot(sizes, qps, marker="o", color="#1f77b4", label="qps")
    axes[0].plot(sizes, p95_s, marker="s", color="#2ca02c", label="p95_seconds")
    axes[0].set_title("Chunk Size: Throughput and p95")
    axes[0].set_xlabel("chunk_size")
    axes[0].set_ylabel("qps / seconds")
    axes[0].grid(alpha=0.3)
    axes[0].legend()

    axes[1].plot(sizes, factual_fail, marker="o", color="#d62728", label="factual_fail")
    axes[1].plot(sizes, open_faith_fail, marker="s", color="#ff7f0e", label="open_faith_fail")
    axes[1].set_title("Chunk Size: Failure Rates")
    axes[1].set_xlabel("chunk_size")
    axes[1].set_ylabel("fail rate")
    axes[1].grid(alpha=0.3)
    axes[1].legend()

    fig.tight_layout()
    fig.savefig(out_path, dpi=180)
    plt.close(fig)


def build_judge_variance_plot(stability_json: Path, out_path: Path) -> None:
    rows = json.loads(stability_json.read_text(encoding="utf-8"))
    rows.sort(key=lambda row: int(row["replicate"]))

    x = [int(row["replicate"]) for row in rows]
    factual = [float(row["factual_fail"]) for row in rows]
    open_faith = [float(row["open_faith_fail"]) for row in rows]

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(x, factual, marker="o", color="#d62728", label="factual_fail")
    ax.plot(x, open_faith, marker="s", color="#ff7f0e", label="open_faith_fail")
    ax.set_title("Judge Variance Across 6 Rescore Replicates")
    ax.set_xlabel("replicate")
    ax.set_ylabel("fail rate")
    ax.set_xticks(x)
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=180)
    plt.close(fig)


def main() -> None:
    root = Path(__file__).resolve().parents[3]

    frontier_metrics_csv = (
        root / "eval/results_revamp/latency_accuracy_frontier_20260218/latency_accuracy_frontier_metrics.csv"
    )
    frontier_manifest_csv = root / "eval/results_revamp/latency_accuracy_frontier_20260218/frontier_manifest.csv"
    chunk_metrics_csv = root / "eval/results_revamp/chunk_size_study_v2_expanded80k/chunk_size_metrics_expanded80k.csv"
    stability_json = (
        root / "eval/results_revamp/judge_stability_single100_baseline_20260218/judge_stability_replicate_metrics.json"
    )

    out_dir = root / "agent_logs/reports/benchmark_figures_20260218"
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = load_metrics_rows(frontier_metrics_csv)
    manifest_rows = load_manifest_rows(frontier_manifest_csv)
    _ = manifest_rows
    chunk_rows = load_chunk_rows(chunk_metrics_csv)

    build_frontier_scatter(rows, out_dir / "frontier_open_faithfulness_scatter.png")
    build_throughput_ranking(rows, out_dir / "frontier_throughput_ranked.png")
    build_retrieval_strategy_tradeoff(rows, out_dir / "retrieval_strategy_tradeoffs.png")
    build_narrative_guardrails_tradeoff(rows, out_dir / "narrative_guardrails_tradeoffs.png")
    build_chunk_tradeoff(chunk_rows, out_dir / "chunk_size_tradeoffs.png")
    build_judge_variance_plot(stability_json, out_dir / "judge_variance_replicates.png")

    print(f"Wrote figures to: {out_dir}")


if __name__ == "__main__":
    main()
