#!/usr/bin/env python3
"""Merge new open200 judge predictions into the baseline labeled audit set."""

from __future__ import annotations

import csv
from pathlib import Path

BASE_AUDIT = Path("agent_logs/judge_audit_faithfulness_open71_single100_open200_20260218.csv")
ITER1_AUDIT = Path("agent_logs/judge_audit_faithfulness_open71_single100_open200_iter1_materiality_20260218.csv")
OUT_AUDIT = Path("agent_logs/judge_audit_faithfulness_open71_single100_open200_iter1_materiality_apples_20260218.csv")

BASE_OPEN200_TOKEN = "open_diverse200_iter0_baseline"
ITER1_OPEN200_TOKEN = "open200_judge_iter3_materiality"


def main() -> None:
    base_rows = list(csv.DictReader(BASE_AUDIT.open("r", encoding="utf-8", newline="")))
    iter_rows = list(csv.DictReader(ITER1_AUDIT.open("r", encoding="utf-8", newline="")))
    if not base_rows:
        raise SystemExit(f"No rows in {BASE_AUDIT}")

    iter_open = {
        (row.get("decision_id") or "").strip(): row
        for row in iter_rows
        if ITER1_OPEN200_TOKEN in (row.get("run_name") or "")
    }

    updated = 0
    missing = 0
    for row in base_rows:
        if BASE_OPEN200_TOKEN not in (row.get("run_name") or ""):
            continue
        decision_id = (row.get("decision_id") or "").strip()
        src = iter_open.get(decision_id)
        if src is None:
            missing += 1
            continue
        row["judge_prediction"] = src.get("judge_prediction", row.get("judge_prediction", ""))
        row["judge_explanation"] = src.get("judge_explanation", row.get("judge_explanation", ""))
        updated += 1

    with OUT_AUDIT.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(base_rows[0].keys()))
        writer.writeheader()
        for row in base_rows:
            writer.writerow(row)

    print(f"Wrote: {OUT_AUDIT}")
    print(f"Updated open200 decisions: {updated}")
    print(f"Missing replacements: {missing}")


if __name__ == "__main__":
    main()
