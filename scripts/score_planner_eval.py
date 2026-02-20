#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from andromeda.eval.io import dump_jsonl, load_jsonl
from andromeda.eval.planner_schema import PlannerEvalPrediction, PlannerEvalQuery, PlannerEvalScore
from andromeda.eval.planner_scoring import score_planner_predictions
from andromeda.eval.runner import save_json


def _csv_rows(queries: list[PlannerEvalQuery], scores: list[PlannerEvalScore]) -> list[dict[str, Any]]:
    """
    Build flattened planner score rows for manual review/audit.
    """

    query_by_id = {item.id: item for item in queries}
    rows: list[dict[str, Any]] = []
    for score in scores:
        query = query_by_id[score.query_id]
        rows.append(
            {
                "query_id": score.query_id,
                "question": score.question,
                "tags": " ".join(query.tags),
                "expected_characteristics": " ".join([item.value for item in score.expected_characteristics]),
                "predicted_characteristics": " ".join([item.value for item in score.predicted_characteristics]),
                "missing_characteristics": " ".join([item.value for item in score.missing_characteristics]),
                "extra_characteristics": " ".join([item.value for item in score.extra_characteristics]),
                "characteristic_exact_match": int(score.characteristic_exact_match),
                "expected_subset_recalled": int(score.expected_subset_recalled),
                "precision": score.precision,
                "recall": score.recall,
                "f1": score.f1,
                "expected_action": (score.expected_action.value if score.expected_action is not None else ""),
                "predicted_action": (score.predicted_action.value if score.predicted_action is not None else ""),
                "action_match": ("" if score.action_match is None else int(score.action_match)),
                "prediction_error": (score.prediction_error or ""),
                "rationale": (query.rationale or ""),
            }
        )
    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    """
    Write review rows to CSV, creating parent directories as needed.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _write_markdown(path: Path, summary: dict[str, object]) -> None:
    """
    Render planner eval summary metrics to a markdown report.
    """

    lines: list[str] = []
    lines.append("# Planner Characteristics Eval Summary")
    lines.append("")
    lines.append("## Topline")
    lines.append("")
    lines.append(f"- n_queries: `{summary['n_queries']}`")
    lines.append(f"- n_predictions: `{summary['n_predictions']}`")
    lines.append(f"- missing_predictions: `{summary['missing_predictions']}`")
    lines.append(f"- prediction_errors: `{summary['prediction_errors']}`")
    lines.append("")
    lines.append(f"- characteristic_exact_match_rate: `{summary['characteristic_exact_match_rate']}`")
    lines.append(f"- expected_subset_recall_rate: `{summary['expected_subset_recall_rate']}`")
    lines.append(f"- macro_precision: `{summary['macro_precision']}`")
    lines.append(f"- macro_recall: `{summary['macro_recall']}`")
    lines.append(f"- macro_f1: `{summary['macro_f1']}`")
    lines.append(f"- micro_precision: `{summary['micro_precision']}`")
    lines.append(f"- micro_recall: `{summary['micro_recall']}`")
    lines.append(f"- micro_f1: `{summary['micro_f1']}`")
    lines.append("")
    lines.append(f"- action_evaluable_n: `{summary['action_evaluable_n']}`")
    lines.append(f"- action_accuracy: `{summary['action_accuracy']}`")
    lines.append("")

    per_characteristic = summary["per_characteristic"]
    if isinstance(per_characteristic, dict):
        lines.append("## Per-characteristic")
        lines.append("")
        lines.append("| characteristic | support | precision | recall | f1 | tp | fp | fn | tn |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
        for key in sorted(per_characteristic.keys()):
            row = per_characteristic[key]
            if not isinstance(row, dict):
                continue
            lines.append(
                "| "
                + str(key)
                + " | "
                + str(row["support"])
                + " | "
                + str(row["precision"])
                + " | "
                + str(row["recall"])
                + " | "
                + str(row["f1"])
                + " | "
                + str(row["tp"])
                + " | "
                + str(row["fp"])
                + " | "
                + str(row["fn"])
                + " | "
                + str(row["tn"])
                + " |"
            )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    """
    CLI entrypoint for planner-characteristics scoring.
    """

    parser = argparse.ArgumentParser(description="Score planner-characteristics eval run artifacts.")
    parser.add_argument("--run-dir", required=True, help="Run directory produced by scripts/run_planner_eval.py")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).expanduser().resolve()
    eval_queries_path = run_dir / "eval_queries.jsonl"
    predictions_path = run_dir / "planner_predictions.jsonl"
    if not eval_queries_path.exists():
        raise SystemExit(f"Missing: {eval_queries_path}")
    if not predictions_path.exists():
        raise SystemExit(f"Missing: {predictions_path}")

    queries = load_jsonl(eval_queries_path, PlannerEvalQuery)
    predictions = load_jsonl(predictions_path, PlannerEvalPrediction)

    scores, summary = score_planner_predictions(queries=queries, predictions=predictions)

    dump_jsonl(scores, run_dir / "planner_scores.jsonl")
    save_json(summary, run_dir / "planner_score_summary.json")

    rows = _csv_rows(queries=queries, scores=scores)
    _write_csv(run_dir / "planner_review.csv", rows)
    _write_markdown(run_dir / "planner_score_summary.md", summary)

    print(f"Wrote: {run_dir / 'planner_scores.jsonl'}")
    print(f"Wrote: {run_dir / 'planner_score_summary.json'}")
    print(f"Wrote: {run_dir / 'planner_review.csv'}")
    print(f"Wrote: {run_dir / 'planner_score_summary.md'}")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
