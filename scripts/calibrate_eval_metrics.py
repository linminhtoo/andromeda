#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import random
from pathlib import Path
from typing import Any

from sklearn.metrics import confusion_matrix, f1_score, precision_score, recall_score


def _parse_binary(raw: str) -> int | None:
    text = (raw or "").strip()
    if text not in {"0", "1"}:
        return None
    return int(text)


def _parse_float(raw: str) -> float | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except Exception:
        return None


def _metric_payload(y_true: list[int], y_pred: list[int]) -> dict[str, float | int]:
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    zero_division: Any = 0
    precision = float(precision_score(y_true, y_pred, pos_label=1, zero_division=zero_division))
    recall = float(recall_score(y_true, y_pred, pos_label=1, zero_division=zero_division))
    f1 = float(f1_score(y_true, y_pred, pos_label=1, zero_division=zero_division))
    accuracy = float((tp + tn) / len(y_true)) if y_true else 0.0
    specificity = float(tn / (tn + fp)) if (tn + fp) else 0.0
    balanced_accuracy = float((recall + specificity) / 2.0)
    return {
        "n": len(y_true),
        "tp": int(tp),
        "fp": int(fp),
        "tn": int(tn),
        "fn": int(fn),
        "accuracy": accuracy,
        "precision_1": precision,
        "recall_1": recall,
        "f1_1": f1,
        "specificity_0": specificity,
        "balanced_accuracy": balanced_accuracy,
    }


def _bootstrap_ci(
    y_true: list[int], y_pred: list[int], *, metric: str, n_bootstrap: int, seed: int
) -> dict[str, float]:
    if not y_true or len(y_true) != len(y_pred):
        return {"mean": math.nan, "ci95_lo": math.nan, "ci95_hi": math.nan}
    rng = random.Random(seed)
    n = len(y_true)
    vals: list[float] = []
    for _ in range(max(1, int(n_bootstrap))):
        idx = [rng.randrange(0, n) for _ in range(n)]
        bt_true = [y_true[i] for i in idx]
        bt_pred = [y_pred[i] for i in idx]
        payload = _metric_payload(bt_true, bt_pred)
        value = payload.get(metric)
        if not isinstance(value, (int, float)):
            raise ValueError(f"Metric is not numeric: {metric}")
        vals.append(float(value))
    vals.sort()
    lo = vals[int(0.025 * (len(vals) - 1))]
    hi = vals[int(0.975 * (len(vals) - 1))]
    return {"mean": float(sum(vals) / len(vals)), "ci95_lo": float(lo), "ci95_hi": float(hi)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate weak auto labels against human labels with bootstrap CIs.")
    parser.add_argument("--labels-csv", required=True, type=Path)
    parser.add_argument("--human-col", default="human_relevance")
    parser.add_argument("--weak-col", default="weak_relevance")
    parser.add_argument("--weak-threshold", type=float, default=0.5)
    parser.add_argument("--n-bootstrap", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out-json", default=None, type=Path)
    args = parser.parse_args()

    labels_csv = args.labels_csv.expanduser().resolve()
    if not labels_csv.exists():
        raise SystemExit(f"Missing labels CSV: {labels_csv}")

    y_true: list[int] = []
    y_pred: list[int] = []
    with labels_csv.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            human = _parse_binary(row.get(args.human_col, ""))
            weak = _parse_float(row.get(args.weak_col, ""))
            if human is None or weak is None:
                continue
            y_true.append(human)
            y_pred.append(1 if weak >= float(args.weak_threshold) else 0)

    if not y_true:
        raise SystemExit("No usable labeled rows (need both human and weak labels).")

    report = {
        "labels_csv": str(labels_csv),
        "human_col": args.human_col,
        "weak_col": args.weak_col,
        "weak_threshold": float(args.weak_threshold),
        "metrics": _metric_payload(y_true, y_pred),
        "bootstrap_ci95": {
            "accuracy": _bootstrap_ci(y_true, y_pred, metric="accuracy", n_bootstrap=args.n_bootstrap, seed=args.seed),
            "precision_1": _bootstrap_ci(
                y_true, y_pred, metric="precision_1", n_bootstrap=args.n_bootstrap, seed=args.seed + 1
            ),
            "recall_1": _bootstrap_ci(
                y_true, y_pred, metric="recall_1", n_bootstrap=args.n_bootstrap, seed=args.seed + 2
            ),
            "f1_1": _bootstrap_ci(y_true, y_pred, metric="f1_1", n_bootstrap=args.n_bootstrap, seed=args.seed + 3),
            "balanced_accuracy": _bootstrap_ci(
                y_true, y_pred, metric="balanced_accuracy", n_bootstrap=args.n_bootstrap, seed=args.seed + 4
            ),
        },
    }

    out_json = args.out_json or labels_csv.with_suffix(".calibration.json")
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote: {out_json}")
    print(json.dumps(report["metrics"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
