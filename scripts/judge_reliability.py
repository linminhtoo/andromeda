#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import random
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sklearn.metrics import cohen_kappa_score, confusion_matrix, f1_score, precision_score, recall_score
from sklearn.model_selection import train_test_split

DEFAULT_JUDGES = ["faithfulness_v1", "factual_correctness_v1", "helpfulness_v1", "focus_v1"]
DEFAULT_KINDS_BY_JUDGE = {
    "faithfulness_v1": {"open_ended"},
    "factual_correctness_v1": {"factual"},
    "helpfulness_v1": {"factual"},
    "focus_v1": {"distractor"},
}


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


@dataclass(frozen=True)
class AuditKey:
    query_id: str
    judge_id: str

    @property
    def decision_id(self) -> str:
        return f"{self.query_id}::{self.judge_id}"


@dataclass(frozen=True)
class Decision:
    decision_id: str
    query_id: str
    judge_id: str
    kind: str
    run_name: str
    run_dir: str
    question: str
    final_answer: str
    top_chunks_compact: str
    judge_prediction: int
    judge_explanation: str
    target_tickers: str
    tags: str
    human_label: str
    human_notes: str
    split: str


def _load_existing_labels(path: Path) -> dict[str, tuple[str, str, str]]:
    """
    Load existing manual labels/notes/splits keyed by decision_id.
    """

    if not path.exists():
        return {}

    out: dict[str, tuple[str, str, str]] = {}
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            decision_id = (row.get("decision_id") or "").strip()
            if not decision_id:
                continue
            label = (row.get("human_label") or "").strip()
            notes = row.get("human_notes") or ""
            split = (row.get("split") or "").strip()
            out[decision_id] = (label, notes, split)
    return out


def _parse_json_map(raw: str) -> dict[str, object]:
    text = (raw or "").strip()
    if not text:
        return {}
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return obj if isinstance(obj, dict) else {}


def _as_label(value: str) -> int | None:
    text = (value or "").strip()
    if text not in {"0", "1"}:
        return None
    return int(text)


def _metric_payload(y_true: list[int], y_pred: list[int]) -> dict[str, float | int]:
    """
    Compute classification metrics for the FAIL class (label=1).
    """

    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    recall_fail = float(recall_score(y_true, y_pred, pos_label=1, zero_division=0))
    specificity = float(tn / (tn + fp)) if (tn + fp) > 0 else 0.0
    accuracy = float((tp + tn) / len(y_true)) if y_true else 0.0
    if not y_true:
        kappa = 0.0
    elif len(set(y_true)) <= 1 and len(set(y_pred)) <= 1:
        kappa = 1.0 if set(y_true) == set(y_pred) else 0.0
    else:
        kappa_raw = float(cohen_kappa_score(y_true, y_pred))
        kappa = 0.0 if math.isnan(kappa_raw) else kappa_raw
    return {
        "n": len(y_true),
        "tp": int(tp),
        "fp": int(fp),
        "tn": int(tn),
        "fn": int(fn),
        "accuracy": accuracy,
        "precision_fail": float(precision_score(y_true, y_pred, pos_label=1, zero_division=0)),
        "recall_fail": recall_fail,
        "f1_fail": float(f1_score(y_true, y_pred, pos_label=1, zero_division=0)),
        "specificity_pass": specificity,
        "balanced_accuracy": float((recall_fail + specificity) / 2.0),
        "cohen_kappa": kappa,
        "judge_fail_rate": float(sum(y_pred) / len(y_pred)) if y_pred else 0.0,
        "human_fail_rate": float(sum(y_true) / len(y_true)) if y_true else 0.0,
    }


def _bootstrap_ci(
    y_true: list[int],
    y_pred: list[int],
    *,
    metric_name: str,
    n_bootstrap: int,
    seed: int,
) -> dict[str, float]:
    """
    Bootstrap percentile confidence interval for a single metric.
    """

    if not y_true or len(y_true) != len(y_pred):
        return {"mean": 0.0, "ci95_lo": 0.0, "ci95_hi": 0.0}

    n = len(y_true)
    rng = random.Random(seed)
    vals: list[float] = []
    for _ in range(max(1, int(n_bootstrap))):
        idx = [rng.randrange(0, n) for _ in range(n)]
        bt_true = [y_true[i] for i in idx]
        bt_pred = [y_pred[i] for i in idx]
        payload = _metric_payload(bt_true, bt_pred)
        value = payload[metric_name]
        vals.append(float(value))

    vals.sort()
    lo_idx = int(0.025 * (len(vals) - 1))
    hi_idx = int(0.975 * (len(vals) - 1))
    return {
        "mean": float(sum(vals) / len(vals)),
        "ci95_lo": float(vals[lo_idx]),
        "ci95_hi": float(vals[hi_idx]),
    }


def _split_labeled_rows(
    rows: list[dict[str, str]],
    *,
    dev_fraction: float,
    seed: int,
    reuse_existing_split: bool,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """
    Build a dev/test split with optional reuse of existing split annotations.
    """

    if reuse_existing_split:
        all_have_split = all((row.get("split") or "") in {"dev", "test"} for row in rows)
        if all_have_split:
            dev_rows = [row for row in rows if (row.get("split") or "") == "dev"]
            test_rows = [row for row in rows if (row.get("split") or "") == "test"]
            if dev_rows and test_rows:
                return dev_rows, test_rows

    labels = [int(row["human_label"]) for row in rows]
    ids = list(range(len(rows)))

    try:
        dev_idx, test_idx = train_test_split(
            ids,
            train_size=float(dev_fraction),
            random_state=int(seed),
            stratify=labels,
        )
    except Exception:
        dev_idx, test_idx = train_test_split(
            ids,
            train_size=float(dev_fraction),
            random_state=int(seed),
            stratify=None,
        )

    dev_set = set(dev_idx)
    dev_rows: list[dict[str, str]] = []
    test_rows: list[dict[str, str]] = []
    for i, row in enumerate(rows):
        if i in dev_set:
            row["split"] = "dev"
            dev_rows.append(row)
        else:
            row["split"] = "test"
            test_rows.append(row)
    return dev_rows, test_rows


def _build_audit(args: argparse.Namespace) -> None:
    target_judges = args.judges if args.judges else list(DEFAULT_JUDGES)
    existing = _load_existing_labels(args.out_csv)

    seen: set[str] = set()
    decisions: list[Decision] = []

    for run_dir in args.run_dirs:
        review_path = run_dir / "review.csv"
        if not review_path.exists():
            raise SystemExit(f"Missing review.csv: {review_path}")
        run_name = run_dir.name

        with review_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                query_id = (row.get("query_id") or "").strip()
                if not query_id:
                    continue
                kind = (row.get("kind") or "").strip()
                pred_map = _parse_json_map(row.get("judge_predictions_json") or "")
                exp_map = _parse_json_map(row.get("judge_explanations_json") or "")

                for judge_id in target_judges:
                    if judge_id not in pred_map:
                        continue
                    if kind not in DEFAULT_KINDS_BY_JUDGE.get(judge_id, {kind}):
                        continue
                    key = AuditKey(query_id=query_id, judge_id=judge_id)
                    if args.dedupe and key.decision_id in seen:
                        continue
                    seen.add(key.decision_id)

                    pred_value = pred_map[judge_id]
                    try:
                        pred = int(pred_value)
                    except Exception:
                        continue

                    label, notes, split = existing.get(key.decision_id, ("", "", ""))
                    decisions.append(
                        Decision(
                            decision_id=key.decision_id,
                            query_id=query_id,
                            judge_id=judge_id,
                            kind=kind,
                            run_name=run_name,
                            run_dir=str(run_dir),
                            question=row.get("question") or "",
                            final_answer=row.get("final_answer") or "",
                            top_chunks_compact=row.get("top_chunks_compact") or "",
                            judge_prediction=pred,
                            judge_explanation=(exp_map.get(judge_id) or "") if isinstance(exp_map, dict) else "",
                            target_tickers=row.get("target_tickers") or "",
                            tags=row.get("tags") or "",
                            human_label=label,
                            human_notes=notes,
                            split=split,
                        )
                    )

    decisions.sort(key=lambda d: (d.judge_id, d.query_id))

    fieldnames = [
        "decision_id",
        "query_id",
        "judge_id",
        "kind",
        "run_name",
        "run_dir",
        "target_tickers",
        "tags",
        "question",
        "final_answer",
        "top_chunks_compact",
        "judge_prediction",
        "judge_explanation",
        "human_label",
        "human_notes",
        "split",
    ]

    args.out_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.out_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for d in decisions:
            writer.writerow(
                {
                    "decision_id": d.decision_id,
                    "query_id": d.query_id,
                    "judge_id": d.judge_id,
                    "kind": d.kind,
                    "run_name": d.run_name,
                    "run_dir": d.run_dir,
                    "target_tickers": d.target_tickers,
                    "tags": d.tags,
                    "question": d.question,
                    "final_answer": d.final_answer,
                    "top_chunks_compact": d.top_chunks_compact,
                    "judge_prediction": d.judge_prediction,
                    "judge_explanation": d.judge_explanation,
                    "human_label": d.human_label,
                    "human_notes": d.human_notes,
                    "split": d.split,
                }
            )

    print(f"Wrote audit CSV: {args.out_csv}")
    print(f"Decisions: {len(decisions)}")
    by_judge: dict[str, int] = {}
    for d in decisions:
        by_judge[d.judge_id] = by_judge.get(d.judge_id, 0) + 1
    print(f"By judge: {by_judge}")


def _evaluate(args: argparse.Namespace) -> None:
    with args.audit_csv.open("r", encoding="utf-8", newline="") as f:
        rows = [row for row in csv.DictReader(f)]

    selected_judges = args.judges if args.judges else sorted({(row.get("judge_id") or "") for row in rows if row})
    out_report: dict[str, object] = {
        "audit_csv": str(args.audit_csv),
        "seed": int(args.seed),
        "dev_fraction": float(args.dev_fraction),
        "n_bootstrap": int(args.n_bootstrap),
        "judges": {},
    }

    for j_idx, judge_id in enumerate(selected_judges):
        judge_rows = [row for row in rows if (row.get("judge_id") or "") == judge_id]
        labeled_rows = [row for row in judge_rows if _as_label(row.get("human_label") or "") is not None]
        if not labeled_rows:
            continue

        dev_rows, test_rows = _split_labeled_rows(
            labeled_rows,
            dev_fraction=args.dev_fraction,
            seed=args.seed + j_idx,
            reuse_existing_split=args.reuse_split,
        )

        def _pack(split_rows: list[dict[str, str]], metric_seed_offset: int) -> dict[str, object]:
            y_true = [int(row["human_label"]) for row in split_rows]
            y_pred = [int(row["judge_prediction"]) for row in split_rows]
            payload = _metric_payload(y_true, y_pred)
            ci_metrics = ["accuracy", "precision_fail", "recall_fail", "f1_fail", "balanced_accuracy"]
            payload["bootstrap_ci95"] = {
                name: _bootstrap_ci(
                    y_true,
                    y_pred,
                    metric_name=name,
                    n_bootstrap=args.n_bootstrap,
                    seed=args.seed + metric_seed_offset + idx,
                )
                for idx, name in enumerate(ci_metrics, start=11)
            }
            return payload

        report_judge = {
            "n_labeled": len(labeled_rows),
            "n_dev": len(dev_rows),
            "n_test": len(test_rows),
            "dev": _pack(dev_rows, metric_seed_offset=101 + j_idx * 100),
            "test": _pack(test_rows, metric_seed_offset=151 + j_idx * 100),
        }
        cast_judges = out_report["judges"]
        if not isinstance(cast_judges, dict):
            raise RuntimeError("internal report type error")
        cast_judges[judge_id] = report_judge

    if args.write_split:
        fieldnames = list(rows[0].keys()) if rows else []
        if "split" not in fieldnames:
            fieldnames.append("split")
        with args.audit_csv.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        print(f"Updated split assignments in: {args.audit_csv}")

    out_path = args.out_json
    if out_path is None:
        out_path = args.audit_csv.parent / f"judge_reliability_report.{_timestamp()}.json"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote report: {out_path}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Judge reliability harness for manual audit + dev/test alignment metrics.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build-audit", help="Build/refresh a decision-level audit CSV from run review files.")
    build.add_argument("--run-dirs", nargs="+", required=True, type=Path, help="Run directories containing review.csv")
    build.add_argument("--out-csv", type=Path, required=True, help="Output decision-level audit CSV")
    build.add_argument("--judges", nargs="*", default=None, help="Judge IDs to include")
    build.add_argument(
        "--dedupe",
        action="store_true",
        default=False,
        help="Dedupe by query_id::judge_id; keep first seen run in --run-dirs order.",
    )

    evaluate = subparsers.add_parser("evaluate", help="Compute judge alignment metrics from labeled audit CSV.")
    evaluate.add_argument("--audit-csv", type=Path, required=True)
    evaluate.add_argument("--out-json", type=Path, default=None)
    evaluate.add_argument("--judges", nargs="*", default=None)
    evaluate.add_argument("--seed", type=int, default=42)
    evaluate.add_argument("--dev-fraction", type=float, default=0.75)
    evaluate.add_argument("--n-bootstrap", type=int, default=1000)
    evaluate.add_argument(
        "--reuse-split",
        action="store_true",
        default=False,
        help="Reuse existing split column when all labeled rows for a judge already have dev/test.",
    )
    evaluate.add_argument(
        "--write-split",
        action="store_true",
        default=False,
        help="Persist generated split assignments back into the audit CSV.",
    )

    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.command == "build-audit":
        _build_audit(args)
        return
    if args.command == "evaluate":
        _evaluate(args)
        return
    raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
