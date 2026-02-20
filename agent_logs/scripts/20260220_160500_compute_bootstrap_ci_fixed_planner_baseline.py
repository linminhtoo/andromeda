#!/usr/bin/env python3
"""Compute bootstrap 95% confidence intervals for fixed-planner baseline metrics."""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any


def load_scores(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def metric_flags(
    rows: list[dict[str, Any]], kind: str, judge_id: str
) -> list[int]:
    values: list[int] = []
    for row in rows:
        if row["kind"] != kind:
            continue
        prediction = None
        for judge in row.get("judges", []):
            if judge.get("judge_id") == judge_id:
                prediction = judge.get("prediction")
                break
        if prediction is None:
            continue
        values.append(1 if int(prediction) == 1 else 0)
    return values


def bootstrap_ci(
    values: list[int], n_bootstrap: int, rng: random.Random
) -> dict[str, float | int]:
    n = len(values)
    if n == 0:
        return {
            "n": 0,
            "fail_rate": 0.0,
            "ci95_lo": 0.0,
            "ci95_hi": 0.0,
        }
    fail_rate = sum(values) / n
    samples: list[float] = []
    for _ in range(n_bootstrap):
        failures = 0
        for _ in range(n):
            failures += values[rng.randrange(n)]
        samples.append(failures / n)
    samples.sort()
    lo = samples[int(0.025 * n_bootstrap)]
    hi = samples[int(0.975 * n_bootstrap)]
    return {
        "n": n,
        "fail_rate": fail_rate,
        "ci95_lo": lo,
        "ci95_hi": hi,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--single-scores", required=True, type=Path)
    parser.add_argument("--multi-scores", required=True, type=Path)
    parser.add_argument("--n-bootstrap", type=int, default=20000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out-json", required=True, type=Path)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    single_rows = load_scores(args.single_scores)
    multi_rows = load_scores(args.multi_scores)

    metric_specs: list[tuple[str, list[int]]] = [
        (
            "single100_factual_fail",
            metric_flags(single_rows, "factual", "factual_correctness_v1"),
        ),
        (
            "single100_factual_helpfulness_fail",
            metric_flags(single_rows, "factual", "helpfulness_v1"),
        ),
        (
            "single100_open_faithfulness_fail",
            metric_flags(single_rows, "open_ended", "faithfulness_v1"),
        ),
        (
            "single100_open_helpfulness_fail",
            metric_flags(single_rows, "open_ended", "helpfulness_v1"),
        ),
        (
            "single100_distractor_focus_fail",
            metric_flags(single_rows, "distractor", "focus_v1"),
        ),
        (
            "single100_distractor_helpfulness_fail",
            metric_flags(single_rows, "distractor", "helpfulness_v1"),
        ),
        (
            "multi60_comparison_fail",
            metric_flags(multi_rows, "comparison", "comparison_v1"),
        ),
        (
            "multi60_comparison_helpfulness_fail",
            metric_flags(multi_rows, "comparison", "helpfulness_v1"),
        ),
    ]

    result = {
        "n_bootstrap": args.n_bootstrap,
        "seed": args.seed,
        "single_scores": str(args.single_scores),
        "multi_scores": str(args.multi_scores),
        "metrics": {
            name: bootstrap_ci(values, args.n_bootstrap, rng)
            for name, values in metric_specs
        },
    }
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
