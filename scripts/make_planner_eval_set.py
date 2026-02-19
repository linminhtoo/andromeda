#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from andromeda.eval.io import dump_jsonl
from andromeda.eval.planner_dataset import build_manual_planner_eval_queries


def main() -> None:
    """
    CLI entrypoint for creating the manual planner-characteristics dataset.
    """

    parser = argparse.ArgumentParser(description="Create manually curated planner-characteristics eval dataset.")
    parser.add_argument(
        "--out",
        default="eval/eval_queries_planner_characteristics_manual100_20260219.jsonl",
        help="Output JSONL path.",
    )
    parser.add_argument("--max-items", type=int, default=None, help="Optional cap on number of queries to write.")
    args = parser.parse_args()

    queries = build_manual_planner_eval_queries()
    if args.max_items is not None:
        queries = queries[: max(0, int(args.max_items))]

    out_path = Path(args.out).expanduser().resolve()
    dump_jsonl(queries, out_path)
    print(f"Wrote {len(queries)} planner eval queries to {out_path}")


if __name__ == "__main__":
    main()
