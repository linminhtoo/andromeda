#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from finrag.eval.io import load_jsonl
from finrag.eval.runner import RunConfig, run_generation, save_json
from finrag.eval.schema import EvalQuery

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _is_multi_ticker_query(query: EvalQuery) -> bool:
    if query.comparison is not None:
        tickers = [t.strip().upper() for t in query.comparison.target_tickers if t and t.strip()]
        return len(set(tickers)) > 1
    if query.distractor is not None:
        tickers = [t.strip().upper() for t in query.distractor.target_tickers if t and t.strip()]
        return len(set(tickers)) > 1
    return False


def main() -> None:
    ap = argparse.ArgumentParser(description="Run an eval query set through finrag.main.RAGService.answer_question().")
    ap.add_argument("--eval-queries", required=True, help="Eval queries JSONL (from scripts/make_eval_set.py).")
    ap.add_argument("--out-dir", required=True, help="Directory to write run artifacts.")
    ap.add_argument("--run-name", default=None, help="Optional run name prefix (e.g. 'baseline').")
    ap.add_argument("--mode", default="normal", help="Generation preset (quick|normal|thinking).")
    ap.add_argument("--concurrency", type=int, default=8, help="Max parallel questions to run (set 1 to disable).")
    ap.add_argument(
        "--parallel-backend",
        choices=["process", "thread"],
        default="process",
        help="Parallel execution backend when concurrency > 1.",
    )
    ap.add_argument(
        "--gpu-ids", nargs="*", type=int, default=None, help="Optional list of GPU IDs to assign to workers."
    )

    # Convenience: point the runner at an existing ingest output dir.
    ap.add_argument(
        "--index-dir",
        default=None,
        help="Directory containing `doc_index.jsonl` (sets FINRAG_DOC_INDEX_PATH for this run).",
    )
    ap.add_argument("--doc-index-path", default=None, help="Overrides env FINRAG_DOC_INDEX_PATH for this run.")
    ap.add_argument("--postgres-dsn", default=None, help="Overrides env POSTGRES_DSN for this run.")

    # Optional overrides.
    ap.add_argument("--top-k-retrieve", type=int, default=None)
    ap.add_argument("--top-k-rerank", type=int, default=None)
    ap.add_argument("--draft-max-tokens", type=int, default=None)
    ap.add_argument("--final-max-tokens", type=int, default=None)
    ap.add_argument("--enable-rerank", type=int, default=None, help="1/0 override (defaults to preset).")
    ap.add_argument("--enable-refine", type=int, default=None, help="1/0 override (defaults to preset).")
    ap.add_argument("--draft-temperature", type=float, default=None)

    # Output controls.
    ap.add_argument("--max-chunks", type=int, default=50)
    ap.add_argument(
        "--query-timeout-s",
        type=float,
        default=120.0,
        help="Optional per-query timeout in seconds for generation (set <=0 to disable).",
    )

    # Filters.
    ap.add_argument("--max-items", type=int, default=None, help="Optional cap on number of queries to run.")
    ap.add_argument(
        "--kinds",
        nargs="*",
        default=None,
        choices=["factual", "open_ended", "refusal", "distractor", "comparison"],
        help="Optional filter (defaults to all).",
    )
    ap.add_argument("--single-ticker-only", action="store_true", help="Keep only single-ticker eval queries.")
    ap.add_argument("--multi-ticker-only", action="store_true", help="Keep only multi-ticker eval queries.")
    ap.add_argument(
        "--disable-finance-tools",
        action="store_true",
        help="Disable yfinance/edgar tool calls during eval generation for faster RAG-focused iteration.",
    )

    args = ap.parse_args()

    if args.single_ticker_only and args.multi_ticker_only:
        raise SystemExit("Use at most one of --single-ticker-only or --multi-ticker-only.")

    if args.index_dir:
        idx = Path(args.index_dir).expanduser().resolve()
        if not idx.exists():
            raise SystemExit(f"--index-dir does not exist: {idx}")
        if args.doc_index_path is None:
            os.environ["FINRAG_DOC_INDEX_PATH"] = str((idx / "doc_index.jsonl").resolve())
    if args.doc_index_path:
        os.environ["FINRAG_DOC_INDEX_PATH"] = str(Path(args.doc_index_path).expanduser().resolve())
    if args.postgres_dsn:
        os.environ["POSTGRES_DSN"] = args.postgres_dsn
    if args.disable_finance_tools:
        os.environ["FINRAG_DISABLE_FINANCE_TOOLS"] = "1"

    queries = load_jsonl(args.eval_queries, EvalQuery)
    if args.kinds:
        wanted = set(args.kinds)
        queries = [q for q in queries if q.kind in wanted]
    if args.single_ticker_only:
        queries = [q for q in queries if not _is_multi_ticker_query(q)]
    if args.multi_ticker_only:
        queries = [q for q in queries if _is_multi_ticker_query(q)]
    if args.max_items is not None:
        queries = queries[: max(0, int(args.max_items))]
    if not queries:
        raise SystemExit("No eval queries to run (check --kinds/--max-items).")

    out_root = Path(args.out_dir).expanduser().resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    stamp = _timestamp()
    run_name = (args.run_name.strip() + ".") if isinstance(args.run_name, str) and args.run_name.strip() else ""
    run_dir = out_root / f"eval_run.{run_name}{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)

    # Persist the exact query set used for this run.
    shutil.copyfile(args.eval_queries, run_dir / "eval_queries.jsonl")

    cfg = RunConfig(
        mode=args.mode,
        top_k_retrieve=args.top_k_retrieve,
        top_k_rerank=args.top_k_rerank,
        draft_max_tokens=args.draft_max_tokens,
        final_max_tokens=args.final_max_tokens,
        enable_rerank=(bool(args.enable_rerank) if args.enable_rerank is not None else None),
        enable_refine=(bool(args.enable_refine) if args.enable_refine is not None else None),
        draft_temperature=args.draft_temperature,
        concurrency=args.concurrency,
        parallel_backend=args.parallel_backend,
        max_chunks=args.max_chunks,
        query_timeout_s=(float(args.query_timeout_s) if args.query_timeout_s is not None else None),
    )

    gpu_ids = [str(gpu) for gpu in args.gpu_ids] if args.gpu_ids else None
    # TODO / FIXME: GPU memory leak in reranker? it is increasing over time...
    summary = run_generation(queries, out_jsonl=run_dir / "generations.jsonl", cfg=cfg, gpu_ids=gpu_ids)
    save_json(cfg.to_dict(), run_dir / "run_config.json")
    save_json(summary, run_dir / "generation_summary.json")

    print(f"Wrote run dir: {run_dir}")
    print(f"Summary: {summary}")


if __name__ == "__main__":
    main()
