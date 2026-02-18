from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any

from andromeda.eval.judges import FACTUAL_CORRECTNESS_V1, HELPFULNESS_V1, JudgeSpec, get_judge_spec, run_judge
from andromeda.eval.metrics import best_numeric_match, cited_doc_ids
from andromeda.eval.schema import EvalGeneration, EvalQuery, EvalScore, JudgeResult, RetrievedChunk
from andromeda.llm.clients import LLMClient
from andromeda.processing.metadata_models import chunk_metadata_from_value

_CHUNK_CITATION_RE = re.compile(r"\[doc=[^\]\s]+\s+chunk=([^\]\s]+)\]")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _truncate(text: str, limit: int) -> str:
    if limit <= 0:
        return text
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _rank(ids: list[str], target: str) -> int | None:
    for i, x in enumerate(ids, start=1):
        if x == target:
            return i
    return None


def _cited_chunk_ids(text: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for match in _CHUNK_CITATION_RE.finditer(text or ""):
        chunk_id = match.group(1).strip()
        if not chunk_id or chunk_id in seen:
            continue
        seen.add(chunk_id)
        out.append(chunk_id)
    return out


def build_context(
    chunks: list[RetrievedChunk],
    *,
    max_chars: int = 80_000,
    prioritized_chunk_ids: list[str] | None = None,
    max_chunk_text_chars: int = 0,
    max_chunk_context_chars: int = 0,
) -> str:
    """
    Build a context string for judge prompts with optional citation prioritization.
    """

    ordered_chunks = list(chunks)
    if prioritized_chunk_ids:
        by_chunk_id: dict[str, RetrievedChunk] = {}
        for ch in ordered_chunks:
            if ch.chunk_id not in by_chunk_id:
                by_chunk_id[ch.chunk_id] = ch

        prioritized: list[RetrievedChunk] = []
        prioritized_set: set[str] = set()
        for chunk_id in prioritized_chunk_ids:
            ch = by_chunk_id.get(chunk_id)
            if ch is None or ch.chunk_id in prioritized_set:
                continue
            prioritized.append(ch)
            prioritized_set.add(ch.chunk_id)

        if prioritized:
            ordered_chunks = prioritized + [ch for ch in ordered_chunks if ch.chunk_id not in prioritized_set]

    parts: list[str] = []
    used = 0
    for ch in ordered_chunks:
        head = f"[doc={ch.doc_id} chunk={ch.chunk_id} score={ch.score:.4f}]"
        body = _truncate((ch.text or ch.preview or "").strip(), max_chunk_text_chars)
        ctx = _truncate((ch.context or "").strip(), max_chunk_context_chars)
        block = head + "\n" + body
        if ctx:
            block += "\n\nContext:\n" + ctx
        block += "\n"
        if used + len(block) > max_chars:
            break
        parts.append(block)
        used += len(block)
    return "\n\n".join(parts).strip()


def _expected_numeric_text(query: EvalQuery) -> str | None:
    if query.kind != "factual" or query.factual is None:
        return None
    n = query.factual.expected_numeric
    bits = [f"value={n.value}"]
    if n.scale:
        bits.append(f"scale={n.scale}")
    if n.unit:
        bits.append(f"unit={n.unit}")
    if n.raw:
        bits.append(f"raw={n.raw.strip()}")
    return ", ".join(bits)


_REFUSAL_HINT_RE = re.compile(
    r"(?i)\b(can(?:not|'t)\s+answer|cannot\s+answer|insufficient\s+information|"
    r"not\s+enough\s+information|not\s+provided\s+in\s+the\s+context|"
    r"based\s+on\s+the\s+provided\s+context|i\s+can\s+only\s+answer\s+using\s+the\s+provided\s+context)\b"
)


def _looks_like_refusal(answer: str) -> bool:
    return bool(_REFUSAL_HINT_RE.search(answer or ""))


def _chunk_tickers(chunks: list[RetrievedChunk]) -> list[str]:
    out: list[str] = []
    for ch in chunks or []:
        parsed = chunk_metadata_from_value(ch.metadata)
        if parsed.doc and parsed.doc.ticker and parsed.doc.ticker.strip():
            out.append(parsed.doc.ticker.strip().upper())
    return out


def _mentions_token(text: str, token: str) -> bool:
    if not token or not token.strip():
        return False
    pat = re.compile(rf"(?i)\\b{re.escape(token.strip())}\\b")
    return bool(pat.search(text or ""))


def _dedupe_judge_specs(judge_specs: list[JudgeSpec]) -> list[JudgeSpec]:
    """
    Keep judge specs in-order while removing duplicate judge IDs.
    """

    out: list[JudgeSpec] = []
    seen: set[str] = set()
    for spec in judge_specs:
        if spec.judge_id in seen:
            continue
        seen.add(spec.judge_id)
        out.append(spec)
    return out


def default_judge_specs_for_query(query: EvalQuery) -> list[JudgeSpec]:
    """
    Return the default judge list for one query kind.
    """

    if query.kind == "factual":
        return [FACTUAL_CORRECTNESS_V1, HELPFULNESS_V1]

    if query.kind == "open_ended" and query.open_ended is not None:
        base = get_judge_spec(query.open_ended.rubric_id or "faithfulness_v1")
        return _dedupe_judge_specs([base, HELPFULNESS_V1])

    if query.kind == "refusal" and query.refusal is not None:
        base = get_judge_spec(query.refusal.rubric_id or "refusal_v1")
        return [base]

    if query.kind == "distractor" and query.distractor is not None:
        base = get_judge_spec(query.distractor.rubric_id or "focus_v1")
        return _dedupe_judge_specs([base, HELPFULNESS_V1])

    if query.kind == "comparison" and query.comparison is not None:
        base = get_judge_spec(query.comparison.rubric_id or "comparison_v1")
        return _dedupe_judge_specs([base, HELPFULNESS_V1])

    return []


def score_one(
    query: EvalQuery,
    gen: EvalGeneration | None,
    *,
    judge_llm: LLMClient | None,
    judge_specs: list[JudgeSpec] | None = None,
    judge_context_chars: int = 80_000,
    judge_timeout_s: float | None = 300.0,
    judge_max_retries: int = 1,
) -> EvalScore:
    resolved_judge_specs = list(judge_specs) if judge_specs is not None else default_judge_specs_for_query(query)

    score = EvalScore(query_id=query.id, kind=query.kind, created_at=_utcnow())

    if gen is None:
        score.answer["status"] = "missing_generation"
        return score

    if gen.error:
        score.answer["status"] = "generation_error"
        score.answer["error"] = gen.error
        return score

    final = (gen.final_answer or "").strip()
    top_chunks = list(gen.top_chunks or [])
    cited_chunk_ids = _cited_chunk_ids(final)
    retrieved_chunk_ids = [c.chunk_id for c in top_chunks]
    retrieved_doc_ids = [c.doc_id for c in top_chunks]
    retrieved_tickers = _chunk_tickers(top_chunks)

    score.retrieval["retrieved_chunks"] = len(retrieved_chunk_ids)
    score.retrieval["retrieved_docs_unique"] = len(set(retrieved_doc_ids))
    if retrieved_tickers:
        score.retrieval["retrieved_tickers_unique"] = len(set(retrieved_tickers))
        score.retrieval["retrieved_tickers_top"] = retrieved_tickers[: min(12, len(retrieved_tickers))]

    if query.kind == "factual" and query.factual is not None:
        gold_chunk = query.factual.golden_evidence.chunk_id
        gold_doc = query.factual.golden_evidence.doc_id

        chunk_rank = _rank(retrieved_chunk_ids, gold_chunk)
        doc_rank = _rank(retrieved_doc_ids, gold_doc)

        score.retrieval.update(
            {
                "gold_chunk_id": gold_chunk,
                "gold_doc_id": gold_doc,
                "gold_chunk_rank": chunk_rank,
                "gold_doc_rank": doc_rank,
                "gold_chunk_mrr": (1.0 / chunk_rank) if chunk_rank else 0.0,
                "gold_doc_mrr": (1.0 / doc_rank) if doc_rank else 0.0,
            }
        )

        expected = query.factual.expected_numeric
        nm = best_numeric_match(final, expected.value, expected_scale=expected.scale)
        score.answer["numeric_matched"] = bool(nm["matched"])
        score.answer["numeric_best_rel_error"] = (
            float(nm["best_rel_error"]) if nm["best_rel_error"] is not None else None
        )
        score.answer["numeric_best_pred"] = nm["best_pred"]

        cited = cited_doc_ids(final)
        score.answer["cited_doc_ids"] = sorted(cited)
        score.answer["cited_gold_doc"] = bool(gold_doc in cited) if gold_doc else False

        if judge_llm is not None:
            ctx = build_context(top_chunks, max_chars=judge_context_chars, prioritized_chunk_ids=cited_chunk_ids)
            expected_s = _expected_numeric_text(query)
            evidence_s = query.factual.golden_evidence.snippet

            for spec in resolved_judge_specs:
                out, raw = run_judge(
                    judge_llm,
                    spec,
                    question=query.question,
                    answer=final,
                    context=ctx,
                    expected=expected_s,
                    evidence=evidence_s,
                    timeout_s=judge_timeout_s,
                    max_retries=judge_max_retries,
                )
                score.judges.append(
                    JudgeResult(
                        judge_id=spec.judge_id,
                        prediction=out.prediction,
                        explanation=out.explanation_sketchpad,
                        raw=raw,
                    )
                )

    # Open-ended-style kinds: judge-based scoring only (plus a few lightweight heuristics).
    if query.kind == "open_ended" and query.open_ended is not None:
        if judge_llm is not None:
            ctx = build_context(top_chunks, max_chars=judge_context_chars, prioritized_chunk_ids=cited_chunk_ids)
            for js in resolved_judge_specs:
                out, raw = run_judge(
                    judge_llm,
                    js,
                    question=query.question,
                    answer=final,
                    context=ctx,
                    timeout_s=judge_timeout_s,
                    max_retries=judge_max_retries,
                )
                score.judges.append(
                    JudgeResult(
                        judge_id=js.judge_id, prediction=out.prediction, explanation=out.explanation_sketchpad, raw=raw
                    )
                )

    if query.kind == "refusal" and query.refusal is not None:
        score.answer["refused_heuristic"] = _looks_like_refusal(final)
        if judge_llm is not None:
            ctx = build_context(top_chunks, max_chars=judge_context_chars, prioritized_chunk_ids=cited_chunk_ids)
            notes = f"reason={query.refusal.reason}"
            if query.refusal.target_ticker:
                notes += f", target_ticker={query.refusal.target_ticker}"
            if query.refusal.target_company:
                notes += f", target_company={query.refusal.target_company}"
            for js in resolved_judge_specs:
                out, raw = run_judge(
                    judge_llm,
                    js,
                    question=query.question,
                    answer=final,
                    context=ctx,
                    notes=notes,
                    timeout_s=judge_timeout_s,
                    max_retries=judge_max_retries,
                )
                score.judges.append(
                    JudgeResult(
                        judge_id=js.judge_id, prediction=out.prediction, explanation=out.explanation_sketchpad, raw=raw
                    )
                )

    if query.kind == "distractor" and query.distractor is not None:
        if query.distractor.target_tickers:
            score.answer["mentions_target_ticker"] = any(
                _mentions_token(final, t) for t in query.distractor.target_tickers
            )
        if judge_llm is not None:
            ctx = build_context(top_chunks, max_chars=judge_context_chars, prioritized_chunk_ids=cited_chunk_ids)
            notes = (
                f"main_question={query.distractor.main_question.strip()}\n"
                f"distractor_kind={query.distractor.distractor_kind}\n"
                f"distractor_text={query.distractor.distractor_text.strip()}"
            )
            for js in resolved_judge_specs:
                out, raw = run_judge(
                    judge_llm,
                    js,
                    question=query.question,
                    answer=final,
                    context=ctx,
                    notes=notes,
                    timeout_s=judge_timeout_s,
                    max_retries=judge_max_retries,
                )
                score.judges.append(
                    JudgeResult(
                        judge_id=js.judge_id, prediction=out.prediction, explanation=out.explanation_sketchpad, raw=raw
                    )
                )

    if query.kind == "comparison" and query.comparison is not None:
        targets = [t.strip().upper() for t in (query.comparison.target_tickers or []) if t and t.strip()]
        if targets:
            score.retrieval["comparison_target_tickers"] = targets
            score.retrieval["comparison_retrieved_tickers_unique"] = sorted(set(retrieved_tickers))
            score.retrieval["comparison_all_targets_retrieved"] = all(t in set(retrieved_tickers) for t in targets)
            score.answer["mentions_all_target_tickers"] = all(_mentions_token(final, t) for t in targets)

        if judge_llm is not None:
            ctx = build_context(top_chunks, max_chars=judge_context_chars, prioritized_chunk_ids=cited_chunk_ids)
            notes = f"target_tickers={targets}"
            for js in resolved_judge_specs:
                out, raw = run_judge(
                    judge_llm,
                    js,
                    question=query.question,
                    answer=final,
                    context=ctx,
                    notes=notes,
                    timeout_s=judge_timeout_s,
                    max_retries=judge_max_retries,
                )
                score.judges.append(
                    JudgeResult(
                        judge_id=js.judge_id, prediction=out.prediction, explanation=out.explanation_sketchpad, raw=raw
                    )
                )

    return score


def summarize(scores: list[EvalScore]) -> dict[str, Any]:
    """
    Small, copy-paste-friendly summary dict.
    """
    out: dict[str, Any] = {"n": len(scores)}
    if not scores:
        return out

    def _mean(vals: list[float]) -> float:
        vals = [v for v in vals if v is not None and not math.isnan(v)]
        return (sum(vals) / len(vals)) if vals else math.nan

    def _is_ok(s: EvalScore) -> bool:
        return "status" not in s.answer or not bool(s.answer["status"])

    def _judge_fail_rate(items: list[EvalScore], judge_id: str) -> float:
        preds: list[float] = []
        for item in items:
            for judge in item.judges:
                if judge.judge_id == judge_id:
                    preds.append(float(judge.prediction))
        return _mean(preds)

    def _judge_rates(items: list[EvalScore]) -> dict[str, float]:
        judge_ids: set[str] = set()
        for item in items:
            for judge in item.judges:
                judge_ids.add(judge.judge_id)

        out_rates: dict[str, float] = {}
        for judge_id in sorted(judge_ids):
            value = _judge_fail_rate(items, judge_id)
            if not math.isnan(value):
                out_rates[judge_id] = value
        return out_rates

    def _attach_judge_metrics(
        out_dict: dict[str, Any], *, prefix: str, items: list[EvalScore], primary_judge_id: str
    ) -> None:
        rates = _judge_rates(items)
        if rates:
            out_dict[f"{prefix}_judge_fail_rates"] = rates
        if primary_judge_id in rates:
            out_dict[f"{prefix}_judge_fail_rate"] = rates[primary_judge_id]
        elif rates:
            first_key = next(iter(rates))
            out_dict[f"{prefix}_judge_fail_rate"] = rates[first_key]
        if HELPFULNESS_V1.judge_id in rates:
            out_dict[f"{prefix}_helpfulness_fail_rate"] = rates[HELPFULNESS_V1.judge_id]

    factual = [s for s in scores if s.kind == "factual"]
    open_ended = [s for s in scores if s.kind == "open_ended"]
    refusal = [s for s in scores if s.kind == "refusal"]
    distractor = [s for s in scores if s.kind == "distractor"]
    comparison = [s for s in scores if s.kind == "comparison"]
    factual_ok = [s for s in factual if _is_ok(s)]
    open_ended_ok = [s for s in open_ended if _is_ok(s)]
    refusal_ok = [s for s in refusal if _is_ok(s)]
    distractor_ok = [s for s in distractor if _is_ok(s)]
    comparison_ok = [s for s in comparison if _is_ok(s)]

    if factual:
        out["factual_n"] = len(factual)
        out["factual_n_ok"] = len(factual_ok)
        out["factual_gold_chunk_hit_rate"] = _mean(
            [1.0 if ("gold_chunk_rank" in s.retrieval and s.retrieval["gold_chunk_rank"]) else 0.0 for s in factual_ok]
        )
        out["factual_numeric_accuracy"] = _mean(
            [1.0 if ("numeric_matched" in s.answer and bool(s.answer["numeric_matched"])) else 0.0 for s in factual_ok]
        )

        _attach_judge_metrics(out, prefix="factual", items=factual_ok, primary_judge_id=FACTUAL_CORRECTNESS_V1.judge_id)

    if open_ended:
        out["open_ended_n"] = len(open_ended)
        out["open_ended_n_ok"] = len(open_ended_ok)
        _attach_judge_metrics(
            out, prefix="open_ended", items=open_ended_ok, primary_judge_id=get_judge_spec("faithfulness_v1").judge_id
        )

    if refusal:
        out["refusal_n"] = len(refusal)
        out["refusal_n_ok"] = len(refusal_ok)
        _attach_judge_metrics(
            out, prefix="refusal", items=refusal_ok, primary_judge_id=get_judge_spec("refusal_v1").judge_id
        )

    if distractor:
        out["distractor_n"] = len(distractor)
        out["distractor_n_ok"] = len(distractor_ok)
        _attach_judge_metrics(
            out, prefix="distractor", items=distractor_ok, primary_judge_id=get_judge_spec("focus_v1").judge_id
        )

    if comparison:
        out["comparison_n"] = len(comparison)
        out["comparison_n_ok"] = len(comparison_ok)
        _attach_judge_metrics(
            out, prefix="comparison", items=comparison_ok, primary_judge_id=get_judge_spec("comparison_v1").judge_id
        )

    return out
