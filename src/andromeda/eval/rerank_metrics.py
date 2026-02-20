from __future__ import annotations

from dataclasses import asdict

from andromeda.eval.retrieval_metrics import RankMetrics


def rerank_uplift(*, pre: RankMetrics, post: RankMetrics) -> dict[str, float | int]:
    """
    Compute pre-vs-post reranking uplift summary.
    """

    rank_shift = 0
    if pre.rank is not None and post.rank is not None:
        rank_shift = pre.rank - post.rank

    win = 1 if rank_shift > 0 else 0
    loss = 1 if rank_shift < 0 else 0
    tie = 1 if rank_shift == 0 else 0

    return {
        "rank_shift": rank_shift,
        "win": win,
        "loss": loss,
        "tie": tie,
        "delta_mrr": post.mrr - pre.mrr,
        "delta_ndcg_at_10": post.ndcg_at_10 - pre.ndcg_at_10,
        "delta_ndcg_at_25": post.ndcg_at_25 - pre.ndcg_at_25,
        "delta_hit_at_5": post.hit_at_5 - pre.hit_at_5,
        "delta_hit_at_10": post.hit_at_10 - pre.hit_at_10,
        "delta_hit_at_25": post.hit_at_25 - pre.hit_at_25,
        "delta_hit_at_40": post.hit_at_40 - pre.hit_at_40,
        "delta_precision_at_5": post.precision_at_5 - pre.precision_at_5,
        "delta_precision_at_10": post.precision_at_10 - pre.precision_at_10,
        "delta_precision_at_25": post.precision_at_25 - pre.precision_at_25,
        "delta_precision_at_40": post.precision_at_40 - pre.precision_at_40,
        "delta_recall_at_5": post.recall_at_5 - pre.recall_at_5,
        "delta_recall_at_10": post.recall_at_10 - pre.recall_at_10,
        "delta_recall_at_25": post.recall_at_25 - pre.recall_at_25,
        "delta_recall_at_40": post.recall_at_40 - pre.recall_at_40,
    }


def prefixed_rank_metrics(prefix: str, metrics: RankMetrics) -> dict[str, float | int | None]:
    """
    Convert RankMetrics to a prefixed flat dict.
    """

    out: dict[str, float | int | None] = {}
    for key, value in asdict(metrics).items():
        out[f"{prefix}_{key}"] = value
    return out
