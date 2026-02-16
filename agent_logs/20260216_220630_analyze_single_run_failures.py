#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            out.append(json.loads(text))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect fail patterns from one scored eval run.")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--max-examples", type=int, default=5)
    args = parser.parse_args()

    run_dir = Path(args.run_dir).expanduser().resolve()
    queries = {row["id"]: row for row in load_jsonl(run_dir / "eval_queries.jsonl")}
    gens = {row["query_id"]: row for row in load_jsonl(run_dir / "generations.jsonl")}
    scores = load_jsonl(run_dir / "scores.jsonl")

    judge_fail_counts: dict[str, Counter[str]] = defaultdict(Counter)
    fail_examples: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    tool_mode_counts: Counter[str] = Counter()

    for score in scores:
        qid = score["query_id"]
        query = queries[qid]
        kind = query["kind"]
        gen = gens.get(qid)
        tool_trace = gen.get("tool_trace") if isinstance(gen, dict) else []

        planned_flags = ""
        if isinstance(tool_trace, list):
            for event in tool_trace:
                if event.get("tool") == "plan_tool_usage":
                    flags = event.get("args") or {}
                    planned_flags = (
                        f"rag={flags.get('use_rag')} yfin={flags.get('use_yfinance')} edgar={flags.get('use_edgar_financials')}"
                    )
                    break
        if planned_flags:
            tool_mode_counts[planned_flags] += 1

        for judge in score.get("judges", []):
            jid = str(judge.get("judge_id") or "")
            pred = int(judge.get("prediction") or 0)
            if pred != 1:
                continue
            judge_fail_counts[kind][jid] += 1
            explanation = str(judge.get("explanation") or "")
            answer = str((gen or {}).get("final_answer") or "")
            if len(fail_examples[f"{kind}:{jid}"]) < args.max_examples:
                fail_examples[f"{kind}:{jid}"].append((qid, explanation[:500], answer[:700]))

    print("run_dir", run_dir)
    print("\nTool usage patterns:")
    for mode, cnt in tool_mode_counts.most_common():
        print(f"  {mode}: {cnt}")

    print("\nJudge fail counts by kind:")
    for kind, counter in judge_fail_counts.items():
        print(f"  {kind}: {dict(counter)}")

    print("\nExamples:")
    for key, items in fail_examples.items():
        print(f"\n== {key} ==")
        for i, (qid, expl, ans) in enumerate(items, 1):
            print(f"[{i}] qid={qid}")
            print(" explanation:", expl.replace("\n", " "))
            print(" answer:", ans.replace("\n", " "))


if __name__ == "__main__":
    main()
