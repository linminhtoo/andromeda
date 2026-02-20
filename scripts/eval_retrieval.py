#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

from andromeda.eval.evidence_support import EntailmentScorer, split_claim_like_units
from andromeda.eval.io import load_jsonl
from andromeda.eval.rerank_metrics import rerank_uplift
from andromeda.eval.retrieval_metrics import metrics_for_ranked_ids
from andromeda.eval.schema import EvalGeneration, EvalQuery


def _mean(values: list[float]) -> float:
    cleaned = [value for value in values if not math.isnan(value)]
    if not cleaned:
        return math.nan
    return sum(cleaned) / len(cleaned)


def _to_float(value: Any) -> float:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return math.nan


def _safe_round(value: float, digits: int = 4) -> float:
    if math.isnan(value):
        return value
    return round(value, digits)


def _dedupe_order(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _evidence_blocks(gen: EvalGeneration, *, max_blocks: int = 10, max_chars: int = 900) -> list[str]:
    blocks: list[str] = []
    for chunk in (gen.top_chunks or [])[:max_blocks]:
        text = (chunk.text or chunk.preview or "").strip()
        if not text:
            continue
        blocks.append(text[:max_chars])
    return blocks


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_markdown(path: Path, summary: dict[str, Any], factual_rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append("# Retrieval + Rerank Benchmark Summary")
    lines.append("")
    lines.append("## Topline")
    lines.append("")
    lines.append(f"- factual_n: `{summary['factual_n']}`")
    lines.append(f"- pre_chunk_mrr: `{summary['pre_chunk_mrr']}`")
    lines.append(f"- post_chunk_mrr: `{summary['post_chunk_mrr']}`")
    lines.append(f"- rerank_chunk_delta_mrr: `{summary['rerank_chunk_delta_mrr']}`")
    lines.append(f"- pre_chunk_precision_at_5: `{summary['pre_chunk_precision_at_5']}`")
    lines.append(f"- post_chunk_precision_at_5: `{summary['post_chunk_precision_at_5']}`")
    lines.append(f"- pre_chunk_precision_at_10: `{summary['pre_chunk_precision_at_10']}`")
    lines.append(f"- post_chunk_precision_at_10: `{summary['post_chunk_precision_at_10']}`")
    lines.append(f"- rerank_chunk_delta_precision_at_5: `{summary['rerank_chunk_delta_precision_at_5']}`")
    lines.append(f"- rerank_chunk_delta_precision_at_10: `{summary['rerank_chunk_delta_precision_at_10']}`")
    lines.append(f"- pre_chunk_recall_at_25: `{summary['pre_chunk_recall_at_25']}`")
    lines.append(f"- post_chunk_recall_at_25: `{summary['post_chunk_recall_at_25']}`")
    lines.append(f"- rerank_chunk_win_rate: `{summary['rerank_chunk_win_rate']}`")
    lines.append(f"- pre_doc_mrr: `{summary['pre_doc_mrr']}`")
    lines.append(f"- post_doc_mrr: `{summary['post_doc_mrr']}`")
    lines.append(f"- rerank_doc_delta_mrr: `{summary['rerank_doc_delta_mrr']}`")
    lines.append(f"- rerank_doc_win_rate: `{summary['rerank_doc_win_rate']}`")
    if "open_ended_nli_support_rate" in summary:
        lines.append(f"- open_ended_nli_support_rate: `{summary['open_ended_nli_support_rate']}`")
        lines.append(f"- open_ended_nli_unsupported_rate: `{summary['open_ended_nli_unsupported_rate']}`")
        lines.append(f"- open_ended_nli_contradiction_rate: `{summary['open_ended_nli_contradiction_rate']}`")
    lines.append("")
    lines.append("## Factual Query Rows (sample)")
    lines.append("")
    lines.append(
        "| query_id | pre_chunk_rank | post_chunk_rank | pre_doc_rank | post_doc_rank | delta_chunk_mrr | delta_doc_mrr |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for row in factual_rows[:20]:
        lines.append(
            f"| `{row['query_id']}` | {row['pre_chunk_rank']} | {row['post_chunk_rank']} | "
            f"{row['pre_doc_rank']} | {row['post_doc_rank']} | {row['delta_chunk_mrr']} | {row['delta_doc_mrr']} |"
        )
    lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute retrieval/rerank subsystem metrics from an eval run dir.")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--enable-nli", action="store_true")
    parser.add_argument("--nli-model", default="cross-encoder/nli-deberta-v3-base")
    parser.add_argument("--nli-max-open-ended", type=int, default=120)
    parser.add_argument("--nli-support-threshold", type=float, default=0.50)
    parser.add_argument("--nli-contradiction-threshold", type=float, default=0.50)
    parser.add_argument("--nli-batch-size", type=int, default=128)
    parser.add_argument("--nli-device", default=None)
    parser.add_argument("--nli-chunk-size", type=int, default=None)
    args = parser.parse_args()

    run_dir = Path(args.run_dir).expanduser().resolve()
    eval_queries = load_jsonl(run_dir / "eval_queries.jsonl", EvalQuery)
    generations = load_jsonl(run_dir / "generations.jsonl", EvalGeneration)
    generation_by_id = {item.query_id: item for item in generations}

    factual_rows: list[dict[str, Any]] = []
    for query in eval_queries:
        if query.kind != "factual" or query.factual is None:
            continue
        generation = generation_by_id.get(query.id)
        if generation is None or generation.error:
            continue
        gold_chunk = query.factual.golden_evidence.chunk_id
        gold_doc = query.factual.golden_evidence.doc_id

        post_chunks = list(generation.top_chunks or [])
        pre_chunks = list(generation.retrieved_chunks or [])
        if not pre_chunks:
            pre_chunks = list(post_chunks)

        post_chunk_ids = [item.chunk_id for item in post_chunks]
        pre_chunk_ids = [item.chunk_id for item in pre_chunks]
        post_doc_ids = _dedupe_order([item.doc_id for item in post_chunks])
        pre_doc_ids = _dedupe_order([item.doc_id for item in pre_chunks])

        pre_chunk_metrics = metrics_for_ranked_ids(
            ranked_ids=pre_chunk_ids, relevant_ids={gold_chunk}, target_id=gold_chunk, relevance_by_id={gold_chunk: 1.0}
        )
        post_chunk_metrics = metrics_for_ranked_ids(
            ranked_ids=post_chunk_ids,
            relevant_ids={gold_chunk},
            target_id=gold_chunk,
            relevance_by_id={gold_chunk: 1.0},
        )
        pre_doc_metrics = metrics_for_ranked_ids(
            ranked_ids=pre_doc_ids, relevant_ids={gold_doc}, target_id=gold_doc, relevance_by_id={gold_doc: 1.0}
        )
        post_doc_metrics = metrics_for_ranked_ids(
            ranked_ids=post_doc_ids, relevant_ids={gold_doc}, target_id=gold_doc, relevance_by_id={gold_doc: 1.0}
        )
        chunk_uplift = rerank_uplift(pre=pre_chunk_metrics, post=post_chunk_metrics)
        doc_uplift = rerank_uplift(pre=pre_doc_metrics, post=post_doc_metrics)
        factual_rows.append(
            {
                "query_id": query.id,
                "pre_chunk_rank": pre_chunk_metrics.rank if pre_chunk_metrics.rank is not None else "",
                "post_chunk_rank": post_chunk_metrics.rank if post_chunk_metrics.rank is not None else "",
                "pre_doc_rank": pre_doc_metrics.rank if pre_doc_metrics.rank is not None else "",
                "post_doc_rank": post_doc_metrics.rank if post_doc_metrics.rank is not None else "",
                "pre_chunk_mrr": pre_chunk_metrics.mrr,
                "post_chunk_mrr": post_chunk_metrics.mrr,
                "pre_doc_mrr": pre_doc_metrics.mrr,
                "post_doc_mrr": post_doc_metrics.mrr,
                "delta_chunk_mrr": chunk_uplift["delta_mrr"],
                "delta_doc_mrr": doc_uplift["delta_mrr"],
                "chunk_win": chunk_uplift["win"],
                "doc_win": doc_uplift["win"],
                "pre_chunk_hit_at_25": pre_chunk_metrics.hit_at_25,
                "post_chunk_hit_at_25": post_chunk_metrics.hit_at_25,
                "pre_doc_hit_at_25": pre_doc_metrics.hit_at_25,
                "post_doc_hit_at_25": post_doc_metrics.hit_at_25,
                "pre_chunk_ndcg_at_10": pre_chunk_metrics.ndcg_at_10,
                "post_chunk_ndcg_at_10": post_chunk_metrics.ndcg_at_10,
                "pre_doc_ndcg_at_10": pre_doc_metrics.ndcg_at_10,
                "post_doc_ndcg_at_10": post_doc_metrics.ndcg_at_10,
                "pre_chunk_precision_at_5": pre_chunk_metrics.precision_at_5,
                "post_chunk_precision_at_5": post_chunk_metrics.precision_at_5,
                "pre_chunk_precision_at_10": pre_chunk_metrics.precision_at_10,
                "post_chunk_precision_at_10": post_chunk_metrics.precision_at_10,
                "pre_chunk_precision_at_25": pre_chunk_metrics.precision_at_25,
                "post_chunk_precision_at_25": post_chunk_metrics.precision_at_25,
                "pre_chunk_recall_at_25": pre_chunk_metrics.recall_at_25,
                "post_chunk_recall_at_25": post_chunk_metrics.recall_at_25,
                "pre_doc_precision_at_5": pre_doc_metrics.precision_at_5,
                "post_doc_precision_at_5": post_doc_metrics.precision_at_5,
                "pre_doc_precision_at_10": pre_doc_metrics.precision_at_10,
                "post_doc_precision_at_10": post_doc_metrics.precision_at_10,
                "pre_doc_precision_at_25": pre_doc_metrics.precision_at_25,
                "post_doc_precision_at_25": post_doc_metrics.precision_at_25,
                "pre_doc_recall_at_25": pre_doc_metrics.recall_at_25,
                "post_doc_recall_at_25": post_doc_metrics.recall_at_25,
                "delta_chunk_precision_at_5": chunk_uplift["delta_precision_at_5"],
                "delta_chunk_precision_at_10": chunk_uplift["delta_precision_at_10"],
                "delta_chunk_precision_at_25": chunk_uplift["delta_precision_at_25"],
                "delta_chunk_recall_at_25": chunk_uplift["delta_recall_at_25"],
                "delta_doc_precision_at_5": doc_uplift["delta_precision_at_5"],
                "delta_doc_precision_at_10": doc_uplift["delta_precision_at_10"],
                "delta_doc_precision_at_25": doc_uplift["delta_precision_at_25"],
                "delta_doc_recall_at_25": doc_uplift["delta_recall_at_25"],
            }
        )

    summary: dict[str, Any] = {
        "run_dir": str(run_dir),
        "factual_n": len(factual_rows),
        "pre_chunk_mrr": _safe_round(_mean([_to_float(row["pre_chunk_mrr"]) for row in factual_rows])),
        "post_chunk_mrr": _safe_round(_mean([_to_float(row["post_chunk_mrr"]) for row in factual_rows])),
        "rerank_chunk_delta_mrr": _safe_round(_mean([_to_float(row["delta_chunk_mrr"]) for row in factual_rows])),
        "rerank_chunk_win_rate": _safe_round(_mean([_to_float(row["chunk_win"]) for row in factual_rows])),
        "pre_doc_mrr": _safe_round(_mean([_to_float(row["pre_doc_mrr"]) for row in factual_rows])),
        "post_doc_mrr": _safe_round(_mean([_to_float(row["post_doc_mrr"]) for row in factual_rows])),
        "rerank_doc_delta_mrr": _safe_round(_mean([_to_float(row["delta_doc_mrr"]) for row in factual_rows])),
        "rerank_doc_win_rate": _safe_round(_mean([_to_float(row["doc_win"]) for row in factual_rows])),
        "pre_chunk_hit_at_25": _safe_round(_mean([_to_float(row["pre_chunk_hit_at_25"]) for row in factual_rows])),
        "post_chunk_hit_at_25": _safe_round(_mean([_to_float(row["post_chunk_hit_at_25"]) for row in factual_rows])),
        "pre_doc_hit_at_25": _safe_round(_mean([_to_float(row["pre_doc_hit_at_25"]) for row in factual_rows])),
        "post_doc_hit_at_25": _safe_round(_mean([_to_float(row["post_doc_hit_at_25"]) for row in factual_rows])),
        "pre_chunk_precision_at_5": _safe_round(
            _mean([_to_float(row["pre_chunk_precision_at_5"]) for row in factual_rows])
        ),
        "post_chunk_precision_at_5": _safe_round(
            _mean([_to_float(row["post_chunk_precision_at_5"]) for row in factual_rows])
        ),
        "pre_chunk_precision_at_10": _safe_round(
            _mean([_to_float(row["pre_chunk_precision_at_10"]) for row in factual_rows])
        ),
        "post_chunk_precision_at_10": _safe_round(
            _mean([_to_float(row["post_chunk_precision_at_10"]) for row in factual_rows])
        ),
        "pre_chunk_precision_at_25": _safe_round(
            _mean([_to_float(row["pre_chunk_precision_at_25"]) for row in factual_rows])
        ),
        "post_chunk_precision_at_25": _safe_round(
            _mean([_to_float(row["post_chunk_precision_at_25"]) for row in factual_rows])
        ),
        "pre_chunk_recall_at_25": _safe_round(
            _mean([_to_float(row["pre_chunk_recall_at_25"]) for row in factual_rows])
        ),
        "post_chunk_recall_at_25": _safe_round(
            _mean([_to_float(row["post_chunk_recall_at_25"]) for row in factual_rows])
        ),
        "pre_doc_precision_at_5": _safe_round(
            _mean([_to_float(row["pre_doc_precision_at_5"]) for row in factual_rows])
        ),
        "post_doc_precision_at_5": _safe_round(
            _mean([_to_float(row["post_doc_precision_at_5"]) for row in factual_rows])
        ),
        "pre_doc_precision_at_10": _safe_round(
            _mean([_to_float(row["pre_doc_precision_at_10"]) for row in factual_rows])
        ),
        "post_doc_precision_at_10": _safe_round(
            _mean([_to_float(row["post_doc_precision_at_10"]) for row in factual_rows])
        ),
        "pre_doc_precision_at_25": _safe_round(
            _mean([_to_float(row["pre_doc_precision_at_25"]) for row in factual_rows])
        ),
        "post_doc_precision_at_25": _safe_round(
            _mean([_to_float(row["post_doc_precision_at_25"]) for row in factual_rows])
        ),
        "pre_doc_recall_at_25": _safe_round(_mean([_to_float(row["pre_doc_recall_at_25"]) for row in factual_rows])),
        "post_doc_recall_at_25": _safe_round(_mean([_to_float(row["post_doc_recall_at_25"]) for row in factual_rows])),
        "rerank_chunk_delta_precision_at_5": _safe_round(
            _mean([_to_float(row["delta_chunk_precision_at_5"]) for row in factual_rows])
        ),
        "rerank_chunk_delta_precision_at_10": _safe_round(
            _mean([_to_float(row["delta_chunk_precision_at_10"]) for row in factual_rows])
        ),
        "rerank_chunk_delta_precision_at_25": _safe_round(
            _mean([_to_float(row["delta_chunk_precision_at_25"]) for row in factual_rows])
        ),
        "rerank_chunk_delta_recall_at_25": _safe_round(
            _mean([_to_float(row["delta_chunk_recall_at_25"]) for row in factual_rows])
        ),
        "rerank_doc_delta_precision_at_5": _safe_round(
            _mean([_to_float(row["delta_doc_precision_at_5"]) for row in factual_rows])
        ),
        "rerank_doc_delta_precision_at_10": _safe_round(
            _mean([_to_float(row["delta_doc_precision_at_10"]) for row in factual_rows])
        ),
        "rerank_doc_delta_precision_at_25": _safe_round(
            _mean([_to_float(row["delta_doc_precision_at_25"]) for row in factual_rows])
        ),
        "rerank_doc_delta_recall_at_25": _safe_round(
            _mean([_to_float(row["delta_doc_recall_at_25"]) for row in factual_rows])
        ),
    }

    if args.enable_nli:
        scorer = EntailmentScorer(
            model_name=args.nli_model,
            batch_size=args.nli_batch_size,
            device=args.nli_device,
            predict_chunk_size=args.nli_chunk_size,
        )
        support_rows: list[dict[str, Any]] = []
        open_ended_queries = [item for item in eval_queries if item.kind == "open_ended"][
            : max(0, args.nli_max_open_ended)
        ]
        for query in open_ended_queries:
            generation = generation_by_id.get(query.id)
            if generation is None or generation.error:
                continue
            claims = split_claim_like_units(generation.final_answer or "")
            if not claims:
                continue
            evidence = _evidence_blocks(generation)
            stats = scorer.score_claims_against_evidence(
                claims=claims,
                evidence_blocks=evidence,
                support_threshold=args.nli_support_threshold,
                contradiction_threshold=args.nli_contradiction_threshold,
            )
            support_rows.append(
                {
                    "query_id": query.id,
                    "claim_count": stats.claim_count,
                    "supported_claim_count": stats.supported_claim_count,
                    "contradicted_claim_count": stats.contradicted_claim_count,
                    "unsupported_claim_count": stats.unsupported_claim_count,
                    "support_rate": stats.support_rate,
                    "contradiction_rate": stats.contradiction_rate,
                    "unsupported_rate": stats.unsupported_rate,
                }
            )
        summary["open_ended_nli_n"] = len(support_rows)
        summary["open_ended_nli_support_rate"] = _safe_round(
            _mean([_to_float(row["support_rate"]) for row in support_rows])
        )
        summary["open_ended_nli_contradiction_rate"] = _safe_round(
            _mean([_to_float(row["contradiction_rate"]) for row in support_rows])
        )
        summary["open_ended_nli_unsupported_rate"] = _safe_round(
            _mean([_to_float(row["unsupported_rate"]) for row in support_rows])
        )
        _write_csv(run_dir / "retrieval_nli_claim_support.csv", support_rows)

    _write_csv(run_dir / "retrieval_rerank_metrics.csv", factual_rows)
    (run_dir / "retrieval_rerank_metrics.json").write_text(
        json.dumps({"summary": summary, "rows": factual_rows}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    _write_markdown(run_dir / "retrieval_rerank_metrics.md", summary, factual_rows)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
