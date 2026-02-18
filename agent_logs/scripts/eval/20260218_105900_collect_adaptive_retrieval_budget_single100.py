#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        rows.append(json.loads(text))
    return rows


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = (len(ordered) - 1) * p
    lo = int(idx)
    hi = min(lo + 1, len(ordered) - 1)
    frac = idx - lo
    return ordered[lo] * (1.0 - frac) + ordered[hi] * frac


def metric(summary: dict[str, Any], *, key: str, sub_key: str, fallback_key: str) -> float:
    group = summary.get(key)
    if isinstance(group, dict) and sub_key in group:
        return float(group[sub_key] or 0.0)
    return float(summary.get(fallback_key, 0.0) or 0.0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect adaptive retrieval budget benchmark metrics.")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out-dir", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest_path = Path(args.manifest).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    rows_out: list[dict[str, Any]] = []
    with manifest_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            run_dir = Path(row["run_dir"]).expanduser().resolve()
            generation_summary = load_json(run_dir / "generation_summary.json")
            score_summary = load_json(run_dir / "score_summary.json")
            generations = load_jsonl(run_dir / "generations.jsonl")

            latencies = []
            for item in generations:
                timing = item.get("timing_ms")
                if isinstance(timing, dict) and timing.get("total_ms") is not None:
                    latencies.append(float(timing["total_ms"]))

            wall_total_ms = float(generation_summary.get("wall_total_ms", 0.0) or 0.0)
            n_ok = int(generation_summary.get("n_ok", 0) or 0)
            throughput_qps = (n_ok / (wall_total_ms / 1000.0)) if wall_total_ms > 0 else 0.0

            rows_out.append(
                {
                    "label": row["label"],
                    "adaptive_budget": row["adaptive_budget"],
                    "run_dir": str(run_dir),
                    "throughput_qps": throughput_qps,
                    "latency_p95_ms": percentile(latencies, 0.95),
                    "factual_correctness_fail_rate": metric(
                        score_summary,
                        key="factual_judge_fail_rates",
                        sub_key="factual_correctness_v1",
                        fallback_key="factual_judge_fail_rate",
                    ),
                    "factual_helpfulness_fail_rate": metric(
                        score_summary,
                        key="factual_judge_fail_rates",
                        sub_key="helpfulness_v1",
                        fallback_key="factual_helpfulness_fail_rate",
                    ),
                    "open_ended_faithfulness_fail_rate": metric(
                        score_summary,
                        key="open_ended_judge_fail_rates",
                        sub_key="faithfulness_v1",
                        fallback_key="open_ended_judge_fail_rate",
                    ),
                    "open_ended_helpfulness_fail_rate": metric(
                        score_summary,
                        key="open_ended_judge_fail_rates",
                        sub_key="helpfulness_v1",
                        fallback_key="open_ended_helpfulness_fail_rate",
                    ),
                }
            )

    if not rows_out:
        raise SystemExit("No benchmark rows found in manifest.")

    csv_path = out_dir / "adaptive_retrieval_budget_single100_metrics.csv"
    md_path = out_dir / "adaptive_retrieval_budget_single100_metrics.md"
    json_path = out_dir / "adaptive_retrieval_budget_single100_metrics.json"

    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows_out[0].keys()))
        writer.writeheader()
        writer.writerows(rows_out)

    json_path.write_text(json.dumps(rows_out, indent=2), encoding="utf-8")

    lines = [
        "# Adaptive Retrieval Budget Benchmark (Single100)",
        "",
        f"- manifest: `{manifest_path}`",
        "",
        "| label | adaptive_budget | qps | p95_ms | factual_fail | factual_help_fail | open_faith_fail | open_help_fail |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows_out:
        lines.append(
            "| {label} | {adaptive_budget} | {throughput_qps:.4f} | {latency_p95_ms:.1f} | "
            "{factual_correctness_fail_rate:.4f} | {factual_helpfulness_fail_rate:.4f} | "
            "{open_ended_faithfulness_fail_rate:.4f} | {open_ended_helpfulness_fail_rate:.4f} |".format(**row)
        )

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote: {csv_path}")
    print(f"Wrote: {json_path}")
    print(f"Wrote: {md_path}")


if __name__ == "__main__":
    main()
