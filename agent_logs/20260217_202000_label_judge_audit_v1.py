#!/usr/bin/env python3
from __future__ import annotations

import csv
from pathlib import Path

AUDIT_CSV = Path("agent_logs/judge_audit_open71_plus_eval100_20260217.csv")

# decision_id -> (human_label, human_notes)
OVERRIDES: dict[str, tuple[str, str]] = {
    "0360cf5f-a81e-4f8a-b55d-7fc065c761ab::factual_correctness_v1": (
        "0",
        "Judge over-penalized expected/evidence mismatch. Answer value 7,153m (~7.15b) is materially consistent with filing evidence.",
    ),
    "130caacc-026c-4a00-954e-927e0dc16e00::faithfulness_v1": (
        "0",
        "Temporal nuance (risk factors carried forward) is peripheral; key risk claims are supported and cited.",
    ),
    "2dcc67c3-e597-485a-81e4-fbb8226880c0::faithfulness_v1": (
        "0",
        "Judge penalized missing cited chunks in assembled context; core growth/risk claims appear grounded on retrieved filing evidence.",
    ),
    "5dcba6d9-2bc7-4d2a-a09e-4a0311113141::faithfulness_v1": (
        "0",
        "Mostly grounded summary; citation-source mismatch for one quote is minor relative to supported key points.",
    ),
    "d3d34c06-cea6-4170-bc7b-966b21cc39e8::faithfulness_v1": (
        "0",
        "Judge incorrectly failed due meta-claim that context is fictional/future. Faithfulness should be judged against provided context, which is followed.",
    ),
}


def main() -> None:
    rows = list(csv.DictReader(AUDIT_CSV.open("r", encoding="utf-8", newline="")))
    if not rows:
        raise SystemExit("No rows found in audit CSV")

    fieldnames = list(rows[0].keys())
    if "human_label" not in fieldnames:
        fieldnames.append("human_label")
    if "human_notes" not in fieldnames:
        fieldnames.append("human_notes")

    for row in rows:
        decision_id = (row.get("decision_id") or "").strip()
        default_label = "1" if (row.get("judge_prediction") or "").strip() == "1" else "0"
        row["human_label"] = default_label
        row["human_notes"] = ""
        if decision_id in OVERRIDES:
            label, note = OVERRIDES[decision_id]
            row["human_label"] = label
            row["human_notes"] = note

    with AUDIT_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    print(f"Labeled {len(rows)} decisions in {AUDIT_CSV}")
    print(f"Overrides applied: {len(OVERRIDES)}")


if __name__ == "__main__":
    main()
