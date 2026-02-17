#!/usr/bin/env python3
"""Merge iteration-2 open200 predictions into baseline labeled audit set."""

from __future__ import annotations

import csv
from pathlib import Path

BASE_AUDIT = Path("agent_logs/judge_audit_faithfulness_open71_single100_open200_20260218.csv")
ITER2_AUDIT_SRC = Path("eval/results_revamp/judge_tuning/eval_run.open200_judge_iter4_materiality_numeric_consistency.20260218_012738/review.csv")
OUT_AUDIT = Path("agent_logs/judge_audit_faithfulness_open71_single100_open200_iter2_materiality_numeric_apples_20260218.csv")
BASE_OPEN200_TOKEN = "open_diverse200_iter0_baseline"


def main() -> None:
    base_rows = list(csv.DictReader(BASE_AUDIT.open("r", encoding="utf-8", newline="")))
    iter_rows = list(csv.DictReader(ITER2_AUDIT_SRC.open("r", encoding="utf-8", newline="")))
    if not base_rows:
        raise SystemExit(f"No rows in {BASE_AUDIT}")
    if not iter_rows:
        raise SystemExit(f"No rows in {ITER2_AUDIT_SRC}")

    iter_pred_by_decision: dict[str, tuple[str, str]] = {}
    for row in iter_rows:
        qid = (row.get("query_id") or "").strip()
        pred_map_raw = row.get("judge_predictions_json") or ""
        exp_map_raw = row.get("judge_explanations_json") or ""
        if not qid:
            continue
        # review.csv already has primary judge columns, but use maps for robustness.
        pred = (row.get("judge_prediction") or "").strip()
        exp = row.get("judge_explanation") or ""
        if pred == "" and "faithfulness_v1" in pred_map_raw:
            # Simple fallback parse if needed.
            marker = '"faithfulness_v1":'
            i = pred_map_raw.find(marker)
            if i != -1:
                tail = pred_map_raw[i + len(marker) :].lstrip()
                pred = tail[:1]
        decision_id = f"{qid}::faithfulness_v1"
        iter_pred_by_decision[decision_id] = (pred, exp)

    updated = 0
    for row in base_rows:
        if BASE_OPEN200_TOKEN not in (row.get("run_name") or ""):
            continue
        decision_id = (row.get("decision_id") or "").strip()
        if decision_id not in iter_pred_by_decision:
            continue
        pred, exp = iter_pred_by_decision[decision_id]
        row["judge_prediction"] = pred
        row["judge_explanation"] = exp
        updated += 1

    with OUT_AUDIT.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(base_rows[0].keys()))
        writer.writeheader()
        for row in base_rows:
            writer.writerow(row)

    print(f"Wrote: {OUT_AUDIT}")
    print(f"Updated open200 decisions: {updated}")


if __name__ == "__main__":
    main()
