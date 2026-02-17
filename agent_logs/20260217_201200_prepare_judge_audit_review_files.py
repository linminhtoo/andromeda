#!/usr/bin/env python3
from __future__ import annotations

import csv
from pathlib import Path

AUDIT_CSV = Path("agent_logs/judge_audit_open71_plus_eval100_20260217.csv")
OUT_DIR = Path("agent_logs/judge_audit_reviews_20260217")


def _sanitize(text: str, limit: int) -> str:
    s = " ".join((text or "").split())
    if len(s) <= limit:
        return s
    return s[: max(0, limit - 3)].rstrip() + "..."


def main() -> None:
    rows = list(csv.DictReader(AUDIT_CSV.open("r", encoding="utf-8", newline="")))
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    by_judge: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        judge = (row.get("judge_id") or "").strip()
        by_judge.setdefault(judge, []).append(row)

    for judge_id, items in by_judge.items():
        items = sorted(items, key=lambda r: r.get("query_id") or "")
        out_path = OUT_DIR / f"{judge_id}.txt"
        with out_path.open("w", encoding="utf-8") as f:
            f.write(f"judge={judge_id} n={len(items)}\n\n")
            for idx, row in enumerate(items, start=1):
                f.write(
                    f"[{idx:03d}] decision_id={row.get('decision_id', '')} pred={row.get('judge_prediction', '')} kind={row.get('kind', '')} tickers={row.get('target_tickers', '')}\n"
                )
                f.write(f"Q: {_sanitize(row.get('question', ''), 340)}\n")
                f.write(f"A: {_sanitize(row.get('final_answer', ''), 520)}\n")
                f.write(f"CTX: {_sanitize(row.get('top_chunks_compact', ''), 520)}\n")
                f.write(f"Judge explanation: {_sanitize(row.get('judge_explanation', ''), 360)}\n")
                f.write("\n")

    print(f"Wrote review files under {OUT_DIR}")


if __name__ == "__main__":
    main()
