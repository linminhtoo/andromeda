from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class RankMetrics:
    """
    Retrieval metrics for one ranked list against a relevant-id set.
    """

    rank: int | None
    mrr: float
    ndcg_at_10: float
    ndcg_at_25: float
    hit_at_5: float
    hit_at_10: float
    hit_at_25: float
    hit_at_40: float
    precision_at_5: float
    precision_at_10: float
    precision_at_25: float
    precision_at_40: float
    recall_at_5: float
    recall_at_10: float
    recall_at_25: float
    recall_at_40: float


def rank_of_id(ranked_ids: list[str], target_id: str) -> int | None:
    """
    Return 1-based rank for a target id in a ranked id list.
    """

    for idx, item in enumerate(ranked_ids, start=1):
        if item == target_id:
            return idx
    return None


def _unique_prefix(items: list[str], limit: int) -> list[str]:
    """
    Return an order-preserving unique top-k prefix.
    """

    if limit <= 0:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in items[:limit]:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def reciprocal_rank(rank: int | None) -> float:
    """
    Compute reciprocal rank from a 1-based rank value.
    """

    if rank is None or rank <= 0:
        return 0.0
    return 1.0 / float(rank)


def hit_at_k(ranked_ids: list[str], relevant_ids: set[str], k: int) -> float:
    """
    Return 1.0 if any relevant id appears in top-k, else 0.0.
    """

    if k <= 0:
        return 0.0
    return 1.0 if any(item in relevant_ids for item in _unique_prefix(ranked_ids, k)) else 0.0


def precision_at_k(ranked_ids: list[str], relevant_ids: set[str], k: int) -> float:
    """
    Compute precision@k for a ranked id list.
    """

    if k <= 0 or not ranked_ids:
        return 0.0
    topk = _unique_prefix(ranked_ids, k)
    if not topk:
        return 0.0
    hits = sum(1 for item in topk if item in relevant_ids)
    return float(hits) / float(len(topk))


def recall_at_k(ranked_ids: list[str], relevant_ids: set[str], k: int) -> float:
    """
    Compute recall@k for a ranked id list.
    """

    if k <= 0 or not relevant_ids:
        return 0.0
    topk = _unique_prefix(ranked_ids, k)
    hits = sum(1 for item in topk if item in relevant_ids)
    return float(hits) / float(len(relevant_ids))


def ndcg_at_k(ranked_ids: list[str], relevance_by_id: dict[str, float], k: int) -> float:
    """
    Compute nDCG@k from an id->relevance map.
    """

    if k <= 0:
        return math.nan
    gains: list[float] = []
    for item in ranked_ids[:k]:
        gains.append(max(0.0, float(relevance_by_id.get(item, 0.0))))

    dcg = 0.0
    for idx, gain in enumerate(gains, start=1):
        denom = math.log2(idx + 1.0)
        dcg += gain / denom

    ideal_gains = sorted((max(0.0, float(v)) for v in relevance_by_id.values()), reverse=True)[:k]
    idcg = 0.0
    for idx, gain in enumerate(ideal_gains, start=1):
        denom = math.log2(idx + 1.0)
        idcg += gain / denom

    if idcg <= 0.0:
        return 0.0
    return dcg / idcg


def metrics_for_ranked_ids(
    *,
    ranked_ids: list[str],
    relevant_ids: Iterable[str],
    target_id: str,
    relevance_by_id: dict[str, float] | None = None,
) -> RankMetrics:
    """
    Build retrieval metrics for one ranked id list.
    """

    relevant_set = {item for item in relevant_ids if item}
    graded = dict(relevance_by_id or {})
    if target_id and target_id not in graded:
        graded[target_id] = 1.0

    rank = rank_of_id(ranked_ids, target_id) if target_id else None
    return RankMetrics(
        rank=rank,
        mrr=reciprocal_rank(rank),
        ndcg_at_10=ndcg_at_k(ranked_ids, graded, 10),
        ndcg_at_25=ndcg_at_k(ranked_ids, graded, 25),
        hit_at_5=hit_at_k(ranked_ids, relevant_set, 5),
        hit_at_10=hit_at_k(ranked_ids, relevant_set, 10),
        hit_at_25=hit_at_k(ranked_ids, relevant_set, 25),
        hit_at_40=hit_at_k(ranked_ids, relevant_set, 40),
        precision_at_5=precision_at_k(ranked_ids, relevant_set, 5),
        precision_at_10=precision_at_k(ranked_ids, relevant_set, 10),
        precision_at_25=precision_at_k(ranked_ids, relevant_set, 25),
        precision_at_40=precision_at_k(ranked_ids, relevant_set, 40),
        recall_at_5=recall_at_k(ranked_ids, relevant_set, 5),
        recall_at_10=recall_at_k(ranked_ids, relevant_set, 10),
        recall_at_25=recall_at_k(ranked_ids, relevant_set, 25),
        recall_at_40=recall_at_k(ranked_ids, relevant_set, 40),
    )
