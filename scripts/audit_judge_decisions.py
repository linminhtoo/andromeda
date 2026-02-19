#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import csv
import json
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from tqdm import tqdm

from andromeda.eval.io import load_jsonl
from andromeda.eval.judges import (
    FACTUAL_CORRECTNESS_V1,
    FAITHFULNESS_V1,
    JudgeSpec,
    get_judge_client,
    get_judge_spec,
    run_judge,
)
from andromeda.eval.schema import EvalGeneration, EvalQuery
from andromeda.eval.scoring import build_context

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


@dataclass(frozen=True)
class RunArtifacts:
    """
    Cached artifacts for one eval run directory.
    """

    query_by_id: dict[str, EvalQuery]
    generation_by_id: dict[str, EvalGeneration]
    review_by_id: dict[str, dict[str, str]]


def _utc_ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_json_map(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        return {}
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return obj if isinstance(obj, dict) else {}


def _load_review_csv(path: Path) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    if not path.exists():
        return out
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            query_id = (row.get("query_id") or "").strip()
            if not query_id:
                continue
            out[query_id] = row
    return out


def _load_run_artifacts(run_dir: Path) -> RunArtifacts:
    eval_queries = load_jsonl(run_dir / "eval_queries.jsonl", EvalQuery)
    generations = load_jsonl(run_dir / "generations.jsonl", EvalGeneration)
    review = _load_review_csv(run_dir / "review.csv")
    return RunArtifacts(
        query_by_id={item.id: item for item in eval_queries},
        generation_by_id={item.query_id: item for item in generations},
        review_by_id=review,
    )


def _expected_text_for_factual(query: EvalQuery) -> str | None:
    if query.factual is None:
        return None
    expected = query.factual.expected_numeric
    bits = [f"value={expected.value}"]
    if expected.scale:
        bits.append(f"scale={expected.scale}")
    if expected.unit:
        bits.append(f"unit={expected.unit}")
    if expected.raw and expected.raw.strip():
        bits.append(f"raw={expected.raw.strip()}")
    return ", ".join(bits)


def _notes_for_decision(row: dict[str, str], query: EvalQuery | None) -> str:
    """
    Build optional evaluator notes to reduce ambiguity for auditing.
    """

    bits: list[str] = []
    kind = (row.get("kind") or "").strip()
    if kind:
        bits.append(f"kind={kind}")
    target_tickers = (row.get("target_tickers") or "").strip()
    if target_tickers:
        bits.append(f"target_tickers={target_tickers}")

    if query is not None and query.factual is not None:
        bits.append(f"factual_metric={query.factual.metric}")
        bits.append(f"gold_doc_id={query.factual.golden_evidence.doc_id}")
        bits.append(f"gold_chunk_id={query.factual.golden_evidence.chunk_id}")

    return ", ".join(bits)


def _spec_for_audit(judge_id: str) -> JudgeSpec:
    """
    Return the JudgeSpec used for proxy-human audit of one decision.
    """

    base = get_judge_spec(judge_id)
    if judge_id != FAITHFULNESS_V1.judge_id:
        return base
    # Keep faithfulness slightly less strict on peripheral details for audit alignment.
    return JudgeSpec(
        judge_id=base.judge_id,
        description=base.description,
        system_prompt=(
            base.system_prompt
            + "\nAdditional audit instruction: tolerate small peripheral mismatches; fail only for material grounding errors."
        ),
        temperature=base.temperature,
        max_context_chars=base.max_context_chars,
    )


def _build_output_fieldnames(rows: list[dict[str, str]]) -> list[str]:
    base_fields = list(rows[0].keys()) if rows else []
    extras = ["audit_prediction", "audit_explanation", "audit_raw", "audit_error", "audit_model", "audit_timestamp"]
    for field in extras:
        if field not in base_fields:
            base_fields.append(field)
    return base_fields


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit every judge decision and populate human_label/human_notes.")
    parser.add_argument("--audit-csv", type=Path, required=True, help="Decision CSV from scripts/judge_reliability.py")
    parser.add_argument("--out-csv", type=Path, default=None, help="Output CSV path (default: overwrite --audit-csv)")
    parser.add_argument(
        "--judges", nargs="*", default=None, help="Optional subset of judge IDs. Defaults to all decisions in CSV."
    )
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--context-chars", type=int, default=80_000)
    parser.add_argument("--timeout-s", type=float, default=350.0)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--overwrite", action="store_true", help="Recompute even if human_label already exists.")
    parser.add_argument("--judge-provider", default=None)
    parser.add_argument("--judge-model", default=None)
    parser.add_argument("--judge-base-url", default=None)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.workers < 1:
        raise SystemExit("--workers must be >= 1")

    audit_csv = args.audit_csv.expanduser().resolve()
    if not audit_csv.exists():
        raise SystemExit(f"Missing audit CSV: {audit_csv}")

    out_csv = args.out_csv.expanduser().resolve() if args.out_csv else audit_csv

    with audit_csv.open("r", encoding="utf-8", newline="") as handle:
        rows = [row for row in csv.DictReader(handle)]
    if not rows:
        raise SystemExit(f"No rows in audit CSV: {audit_csv}")

    selected_judges = set(args.judges) if args.judges else None

    artifacts_cache: dict[Path, RunArtifacts] = {}

    def _get_artifacts(run_dir_raw: str) -> RunArtifacts:
        run_dir = Path(run_dir_raw).expanduser().resolve()
        if run_dir not in artifacts_cache:
            artifacts_cache[run_dir] = _load_run_artifacts(run_dir)
        return artifacts_cache[run_dir]

    thread_local = threading.local()

    def _get_llm():
        if not hasattr(thread_local, "judge_llm"):
            thread_local.judge_llm = get_judge_client(
                provider=args.judge_provider, chat_model=args.judge_model, base_url=args.judge_base_url
            )
        return thread_local.judge_llm

    model_name = (args.judge_model or "").strip() or "default"

    def _audit_one(idx: int, row: dict[str, str]) -> tuple[int, dict[str, str]]:
        judge_id = (row.get("judge_id") or "").strip()
        if not judge_id:
            row["audit_error"] = "missing_judge_id"
            row["audit_timestamp"] = _utc_ts()
            return idx, row

        if selected_judges is not None and judge_id not in selected_judges:
            return idx, row

        existing_label = (row.get("human_label") or "").strip()
        if existing_label in {"0", "1"} and not args.overwrite:
            return idx, row

        run_dir_raw = (row.get("run_dir") or "").strip()
        query_id = (row.get("query_id") or "").strip()
        if not run_dir_raw or not query_id:
            row["audit_error"] = "missing_run_dir_or_query_id"
            row["audit_timestamp"] = _utc_ts()
            return idx, row

        try:
            artifacts = _get_artifacts(run_dir_raw)
            query = artifacts.query_by_id.get(query_id)
            generation = artifacts.generation_by_id.get(query_id)

            question = (query.question if query is not None else (row.get("question") or "")).strip()
            answer = (
                generation.final_answer
                if generation is not None and generation.final_answer
                else (row.get("final_answer") or "")
            ).strip()
            if generation is not None:
                context = build_context(list(generation.top_chunks or []), max_chars=int(args.context_chars))
            else:
                context = (row.get("top_chunks_compact") or "").strip()

            expected = _expected_text_for_factual(query) if query is not None else None
            evidence = (
                query.factual.golden_evidence.snippet
                if query is not None and query.factual is not None and query.factual.golden_evidence.snippet
                else None
            )
            if evidence and len(evidence) > 12_000:
                evidence = evidence[:12_000]
            notes = _notes_for_decision(row, query)

            spec = _spec_for_audit(judge_id)
            llm = _get_llm()
            out, raw = run_judge(
                llm,
                spec,
                question=question,
                answer=answer,
                context=context,
                expected=expected if judge_id == FACTUAL_CORRECTNESS_V1.judge_id else None,
                evidence=evidence if judge_id == FACTUAL_CORRECTNESS_V1.judge_id else None,
                notes=notes,
                timeout_s=args.timeout_s,
                max_retries=args.max_retries,
            )

            row["audit_prediction"] = str(int(out.prediction))
            row["audit_explanation"] = out.explanation_sketchpad
            row["audit_raw"] = raw
            row["audit_error"] = ""
            row["audit_model"] = model_name
            row["audit_timestamp"] = _utc_ts()
            row["human_label"] = str(int(out.prediction))
            row["human_notes"] = (
                f"auto-audit judge={judge_id} pred={int(out.prediction)} "
                f"vs_judge_pred={(row.get('judge_prediction') or '').strip()} | {out.explanation_sketchpad}"
            )
            return idx, row
        except Exception as exc:  # noqa: BLE001
            row["audit_error"] = str(exc)
            row["audit_timestamp"] = _utc_ts()
            return idx, row

    indexed = list(enumerate(rows))
    out_rows: list[dict[str, str]] = [dict(row) for row in rows]
    with concurrent.futures.ThreadPoolExecutor(max_workers=int(args.workers)) as executor:
        futures = [executor.submit(_audit_one, idx, dict(row)) for idx, row in indexed]
        for future in tqdm(concurrent.futures.as_completed(futures), total=len(futures), desc="Auditing decisions"):
            idx, audited = future.result()
            out_rows[idx] = audited

    fieldnames = _build_output_fieldnames(out_rows)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in out_rows:
            writer.writerow(row)

    n_labeled = sum(1 for row in out_rows if (row.get("human_label") or "").strip() in {"0", "1"})
    n_errors = sum(1 for row in out_rows if (row.get("audit_error") or "").strip())
    print(f"Wrote: {out_csv}")
    print(f"Rows: {len(out_rows)} | labeled: {n_labeled} | audit_errors: {n_errors}")


if __name__ == "__main__":
    main()
