#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from andromeda.eval.io import load_jsonl
from andromeda.eval.schema import EvalGeneration, EvalQuery


def _load(path: Path) -> tuple[dict[str, EvalQuery], dict[str, EvalGeneration]]:
    queries = load_jsonl(path / "eval_queries.jsonl", EvalQuery)
    generations = load_jsonl(path / "generations.jsonl", EvalGeneration)
    return {q.id: q for q in queries}, {g.query_id: g for g in generations}


def _preview(text: str, limit: int = 700) -> str:
    t = (text or "").strip().replace("\n", " ")
    if len(t) <= limit:
        return t
    return t[: max(0, limit - 1)].rstrip() + "…"


def _weak_label(query: EvalQuery, chunk_id: str, doc_id: str) -> float | None:
    if query.factual is None:
        return None
    if chunk_id == query.factual.golden_evidence.chunk_id:
        return 1.0
    if doc_id == query.factual.golden_evidence.doc_id:
        return 0.7
    return 0.0


def _row(
    *,
    run_name: str,
    query: EvalQuery,
    chunk_id: str,
    doc_id: str,
    rank_pre: int | None,
    rank_post: int | None,
    score_pre: float | None,
    score_post: float | None,
    text_preview: str,
) -> dict[str, Any]:
    weak = _weak_label(query, chunk_id, doc_id)
    return {
        "run_name": run_name,
        "query_id": query.id,
        "kind": query.kind,
        "question": query.question,
        "chunk_id": chunk_id,
        "doc_id": doc_id,
        "rank_pre": "" if rank_pre is None else rank_pre,
        "rank_post": "" if rank_post is None else rank_post,
        "in_pre": int(rank_pre is not None),
        "in_post": int(rank_post is not None),
        "score_pre": "" if score_pre is None else score_pre,
        "score_post": "" if score_post is None else score_post,
        "weak_relevance": "" if weak is None else weak,
        "text_preview": text_preview,
        "human_relevance": "",
        "human_notes": "",
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build pooled retrieval chunk label candidates from eval run artifacts.")
    parser.add_argument("--run-dirs", nargs="+", required=True, type=Path)
    parser.add_argument("--out-csv", required=True, type=Path)
    parser.add_argument("--out-json", default=None, type=Path)
    parser.add_argument("--pre-k", type=int, default=30)
    parser.add_argument("--post-k", type=int, default=30)
    parser.add_argument(
        "--kinds",
        nargs="*",
        default=["factual", "open_ended", "comparison", "distractor"],
        choices=["factual", "open_ended", "comparison", "distractor", "refusal"],
    )
    args = parser.parse_args()

    wanted = set(args.kinds or [])
    rows: list[dict[str, Any]] = []
    per_run_stats: dict[str, dict[str, Any]] = {}

    for run_dir in args.run_dirs:
        run_path = run_dir.expanduser().resolve()
        query_by_id, generation_by_id = _load(run_path)
        run_rows_before = len(rows)

        for query_id, query in query_by_id.items():
            if query.kind not in wanted:
                continue
            generation = generation_by_id.get(query_id)
            if generation is None or generation.error:
                continue

            pre_chunks = list(generation.retrieved_chunks or [])[: max(0, int(args.pre_k))]
            post_chunks = list(generation.top_chunks or [])[: max(0, int(args.post_k))]
            if not pre_chunks and not post_chunks:
                continue

            pre_index: dict[str, tuple[int, float | None, str]] = {}
            for idx, chunk in enumerate(pre_chunks, start=1):
                if chunk.chunk_id in pre_index:
                    continue
                pre_index[chunk.chunk_id] = (idx, float(chunk.score), chunk.doc_id)

            post_index: dict[str, tuple[int, float | None, str]] = {}
            for idx, chunk in enumerate(post_chunks, start=1):
                if chunk.chunk_id in post_index:
                    continue
                post_index[chunk.chunk_id] = (idx, float(chunk.score), chunk.doc_id)

            merged_ids = list(dict.fromkeys(list(pre_index.keys()) + list(post_index.keys())))
            chunk_text_by_id: dict[str, str] = {}
            for chunk in pre_chunks + post_chunks:
                if chunk.chunk_id not in chunk_text_by_id:
                    chunk_text_by_id[chunk.chunk_id] = chunk.text or chunk.preview or ""

            for chunk_id in merged_ids:
                pre_meta = pre_index.get(chunk_id)
                post_meta = post_index.get(chunk_id)
                doc_id = (post_meta[2] if post_meta is not None else (pre_meta[2] if pre_meta is not None else ""))
                rows.append(
                    _row(
                        run_name=run_path.name,
                        query=query,
                        chunk_id=chunk_id,
                        doc_id=doc_id,
                        rank_pre=(pre_meta[0] if pre_meta is not None else None),
                        rank_post=(post_meta[0] if post_meta is not None else None),
                        score_pre=(pre_meta[1] if pre_meta is not None else None),
                        score_post=(post_meta[1] if post_meta is not None else None),
                        text_preview=_preview(chunk_text_by_id.get(chunk_id, "")),
                    )
                )

        per_run_stats[run_path.name] = {
            "n_queries": len(query_by_id),
            "pooled_rows": len(rows) - run_rows_before,
        }

    _write_csv(args.out_csv, rows)
    out_json = args.out_json or args.out_csv.with_suffix(".stats.json")
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(
        json.dumps(
            {
                "run_dirs": [str(item.expanduser().resolve()) for item in args.run_dirs],
                "kinds": sorted(wanted),
                "pre_k": int(args.pre_k),
                "post_k": int(args.post_k),
                "rows": len(rows),
                "per_run": per_run_stats,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Wrote: {args.out_csv}")
    print(f"Wrote: {out_json}")
    print(f"Rows: {len(rows)}")


if __name__ == "__main__":
    main()

