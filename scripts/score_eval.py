#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import csv
import json
import threading
from tqdm import tqdm
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from andromeda.eval.io import dump_jsonl, load_jsonl
from andromeda.eval.judges import get_judge_client
from andromeda.eval.schema import EvalGeneration, EvalQuery, EvalScore
from andromeda.eval.scoring import score_one, summarize
from andromeda.eval.runner import save_json

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def _compact_top_chunks(gen: EvalGeneration, *, max_chars: int = 2400, max_chunks: int = 6) -> str:
    parts: list[str] = []
    used = 0
    for ch in (gen.top_chunks or [])[:max_chunks]:
        head = f"[doc={ch.doc_id} chunk={ch.chunk_id} score={ch.score:.4f}]"
        body = (ch.preview or ch.text or "").strip().replace("\n", " ")
        body = " ".join(body.split())
        block = head + " " + body
        if used + len(block) > max_chars:
            break
        parts.append(block)
        used += len(block)
    return "\n".join(parts).strip()


def _tool_trace_summary(gen: EvalGeneration) -> dict[str, Any]:
    tool_names: list[str] = []
    for event in gen.tool_trace or []:
        if not isinstance(event, dict):
            continue
        name = str(event.get("tool") or "").strip()
        if name:
            tool_names.append(name)

    result_tools: list[str] = []
    for item in gen.tool_results or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("tool") or "").strip()
        if name:
            result_tools.append(name)

    all_tools = sorted(set(tool_names + result_tools))
    lowered = [name.lower() for name in all_tools]
    return {
        "tool_event_count": len(tool_names),
        "tool_names": " ".join(all_tools),
        "tool_results_count": len(gen.tool_results or []),
        "finance_event_count": sum(1 for name in lowered if "finance" in name or "edgar" in name or "yfinance" in name),
        "used_yfinance": any("yfinance" in name for name in lowered),
        "used_edgar_financials": any("edgar" in name for name in lowered),
    }


def _write_review_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _load_existing_human_labels(path: Path) -> dict[str, tuple[str, str]]:
    if not path.exists():
        return {}
    out: dict[str, tuple[str, str]] = {}
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            r = csv.DictReader(f)
            for row in r:
                qid = (row.get("query_id") or row.get("id") or "").strip()
                if not qid:
                    continue
                lab = (row.get("human_label") or "").strip()
                notes = row.get("human_notes") or ""
                if lab == "" and notes == "":
                    continue
                out[qid] = (lab, notes)
    except Exception:
        return {}
    return out


def _is_multi_ticker_query(query: EvalQuery) -> bool:
    if query.comparison is not None:
        tickers = [t.strip().upper() for t in query.comparison.target_tickers if t and t.strip()]
        return len(set(tickers)) > 1
    if query.distractor is not None:
        tickers = [t.strip().upper() for t in query.distractor.target_tickers if t and t.strip()]
        return len(set(tickers)) > 1
    return False


def _judge_maps(score: EvalScore) -> tuple[dict[str, int], dict[str, str]]:
    """
    Build judge-id keyed prediction and explanation maps for one score row.
    """

    predictions: dict[str, int] = {}
    explanations: dict[str, str] = {}
    for judge in score.judges:
        predictions[judge.judge_id] = int(judge.prediction)
        explanations[judge.judge_id] = judge.explanation if judge.explanation is not None else ""
    return predictions, explanations


def main() -> None:
    ap = argparse.ArgumentParser(description="Score a run directory produced by scripts/run_eval.py.")
    ap.add_argument("--run-dir", required=True, help="Run directory containing eval_queries.jsonl + generations.jsonl.")
    ap.add_argument("--no-judge", action="store_true", help="Skip LLM-as-judge scoring.")
    ap.add_argument("--judge-provider", default=None)
    ap.add_argument("--judge-model", default=None)
    ap.add_argument("--judge-base-url", default=None)
    ap.add_argument("--judge-context-chars", type=int, default=80_000)
    ap.add_argument(
        "--judge-timeout-s",
        type=float,
        default=300.0,
        help="Per-judge-call timeout in seconds (set <=0 to disable provider timeout override).",
    )
    ap.add_argument("--judge-max-retries", type=int, default=1, help="Retry count after the first failed judge call.")
    ap.add_argument(
        "--judge-workers",
        type=int,
        default=1,
        help="Thread parallelism for judge API calls (only used when judge is enabled).",
    )
    ap.add_argument("--max-items", type=int, default=None)
    ap.add_argument(
        "--kinds",
        nargs="*",
        default=None,
        choices=["factual", "open_ended", "refusal", "distractor", "comparison"],
        help="Optional filter (defaults to all).",
    )
    ap.add_argument("--single-ticker-only", action="store_true", help="Keep only single-ticker eval queries.")
    ap.add_argument("--multi-ticker-only", action="store_true", help="Keep only multi-ticker eval queries.")
    args = ap.parse_args()

    if args.single_ticker_only and args.multi_ticker_only:
        raise SystemExit("Use at most one of --single-ticker-only or --multi-ticker-only.")

    run_dir = Path(args.run_dir).expanduser().resolve()
    eval_queries_path = run_dir / "eval_queries.jsonl"
    generations_path = run_dir / "generations.jsonl"
    if not eval_queries_path.exists():
        raise SystemExit(f"Missing: {eval_queries_path}")
    if not generations_path.exists():
        raise SystemExit(f"Missing: {generations_path}")

    queries = load_jsonl(eval_queries_path, EvalQuery)
    generations = load_jsonl(generations_path, EvalGeneration)

    gens_by_id = {g.query_id: g for g in generations}

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
        raise SystemExit("No items to score (check --kinds/--max-items).")

    if args.judge_workers < 1:
        raise SystemExit("--judge-workers must be >= 1")
    if args.judge_max_retries < 0:
        raise SystemExit("--judge-max-retries must be >= 0")

    judge_client_kwargs = {
        "provider": args.judge_provider,
        "chat_model": args.judge_model,
        "base_url": args.judge_base_url,
    }

    if args.no_judge or args.judge_workers == 1:
        judge_llm = (
            None
            if args.no_judge
            else get_judge_client(
                provider=judge_client_kwargs["provider"],
                chat_model=judge_client_kwargs["chat_model"],
                base_url=judge_client_kwargs["base_url"],
            )
        )
        scores: list[EvalScore] = []
        for q in tqdm(queries, total=len(queries), desc="Scoring eval queries"):
            scores.append(
                score_one(
                    q,
                    gens_by_id.get(q.id),
                    judge_llm=judge_llm,
                    judge_context_chars=args.judge_context_chars,
                    judge_timeout_s=args.judge_timeout_s,
                    judge_max_retries=args.judge_max_retries,
                )
            )
    else:
        thread_local = threading.local()

        def _score_query_threadsafe(q: EvalQuery) -> EvalScore:
            if not hasattr(thread_local, "judge_llm"):
                thread_local.judge_llm = get_judge_client(
                    provider=judge_client_kwargs["provider"],
                    chat_model=judge_client_kwargs["chat_model"],
                    base_url=judge_client_kwargs["base_url"],
                )
            return score_one(
                q,
                gens_by_id.get(q.id),
                judge_llm=thread_local.judge_llm,
                judge_context_chars=args.judge_context_chars,
                judge_timeout_s=args.judge_timeout_s,
                judge_max_retries=args.judge_max_retries,
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=args.judge_workers) as ex:
            fut_to_idx = {ex.submit(_score_query_threadsafe, q): i for i, q in enumerate(queries)}
            scored: list[EvalScore | None] = [None] * len(queries)
            for fut in tqdm(
                concurrent.futures.as_completed(fut_to_idx),
                total=len(fut_to_idx),
                desc=f"Scoring eval queries with {args.judge_workers} judge workers",
            ):
                i = fut_to_idx[fut]
                scored[i] = fut.result()
            if any(s is None for s in scored):
                raise RuntimeError("Internal error: missing score result")
            scores = [s for s in scored if s is not None]

    summary = summarize(scores)

    dump_jsonl(scores, run_dir / "scores.jsonl")
    save_json(summary, run_dir / "score_summary.json")

    # A merged, single-record-per-case JSONL is easiest to grep through.
    cases: list[dict[str, Any]] = []
    review_rows: list[dict[str, Any]] = []
    # NOTE: this serves to preserve any existing human labels/notes from prior runs of score_eval.py
    existing_labels = _load_existing_human_labels(run_dir / "review.csv")
    for q, s in tqdm(zip(queries, scores), total=len(queries), desc="Building cases/review.csv"):
        g = gens_by_id.get(q.id)
        case = {
            "query": q.model_dump(mode="json"),
            "generation": (g.model_dump(mode="json") if g is not None else None),
            "score": s.model_dump(mode="json"),
        }
        cases.append(case)

        expected = q.factual.expected_numeric if q.factual is not None else None
        gold = q.factual.golden_evidence if q.factual is not None else None
        judge0 = s.judges[0] if s.judges else None
        judge_preds, judge_explanations = _judge_maps(s)
        helpfulness_prediction = judge_preds["helpfulness_v1"] if "helpfulness_v1" in judge_preds else ""
        helpfulness_explanation = judge_explanations["helpfulness_v1"] if "helpfulness_v1" in judge_explanations else ""
        tool_summary = _tool_trace_summary(g) if g is not None else {}
        target_tickers: list[str] = []
        if q.open_ended is not None and q.open_ended.target_ticker:
            target_tickers.append(q.open_ended.target_ticker)
        if q.distractor is not None:
            target_tickers.extend(list(q.distractor.target_tickers or []))
        if q.comparison is not None:
            target_tickers.extend(list(q.comparison.target_tickers or []))
        if q.refusal is not None and q.refusal.target_ticker:
            target_tickers.append(q.refusal.target_ticker)
        target_tickers_s = " ".join(sorted({t.strip().upper() for t in target_tickers if t and t.strip()}))
        review_rows.append(
            {
                "query_id": q.id,
                "kind": q.kind,
                "question": q.question,
                "tags": " ".join([t for t in (q.tags or []) if t]),
                "target_tickers": target_tickers_s,
                "refusal_reason": (q.refusal.reason if q.refusal is not None else ""),
                "distractor_kind": (q.distractor.distractor_kind if q.distractor is not None else ""),
                "expected_value": (expected.value if expected is not None else ""),
                "expected_scale": (expected.scale if expected is not None else ""),
                "expected_raw": (expected.raw if expected is not None and expected.raw else ""),
                "gold_doc_id": (gold.doc_id if gold is not None else ""),
                "gold_chunk_id": (gold.chunk_id if gold is not None else ""),
                "gold_section_path": (gold.section_path if gold is not None and gold.section_path else ""),
                "gold_chunk_rank": s.retrieval.get("gold_chunk_rank", ""),
                "numeric_matched": s.answer.get("numeric_matched", ""),
                "numeric_best_pred": s.answer.get("numeric_best_pred", ""),
                "numeric_best_rel_error": s.answer.get("numeric_best_rel_error", ""),
                "cited_gold_doc": s.answer.get("cited_gold_doc", ""),
                "judge_id": (judge0.judge_id if judge0 is not None else ""),
                "judge_prediction": (judge0.prediction if judge0 is not None else ""),
                "judge_explanation": (judge0.explanation if judge0 is not None and judge0.explanation else ""),
                "judge_predictions_json": json.dumps(judge_preds, ensure_ascii=False, sort_keys=True),
                "judge_explanations_json": json.dumps(judge_explanations, ensure_ascii=False, sort_keys=True),
                "helpfulness_prediction": helpfulness_prediction,
                "helpfulness_explanation": helpfulness_explanation,
                "tool_event_count": tool_summary.get("tool_event_count", ""),
                "tool_names": tool_summary.get("tool_names", ""),
                "tool_results_count": tool_summary.get("tool_results_count", ""),
                "finance_event_count": tool_summary.get("finance_event_count", ""),
                "used_yfinance": tool_summary.get("used_yfinance", ""),
                "used_edgar_financials": tool_summary.get("used_edgar_financials", ""),
                "final_answer": (g.final_answer if g is not None and g.final_answer else ""),
                "top_chunks_compact": (_compact_top_chunks(g) if g is not None else ""),
                "human_label": (existing_labels.get(q.id, ("", ""))[0]),
                "human_notes": (existing_labels.get(q.id, ("", ""))[1]),
            }
        )

    dump_jsonl(cases, run_dir / "cases.jsonl")
    _write_review_csv(review_rows, run_dir / "review.csv")

    print(f"Wrote: {run_dir / 'scores.jsonl'}")
    print(f"Wrote: {run_dir / 'cases.jsonl'}")
    print(f"Wrote: {run_dir / 'review.csv'}")
    print(f"Summary: {summary}")


if __name__ == "__main__":
    main()
