from __future__ import annotations

from andromeda.eval.evidence_support import citation_support_summary
from andromeda.eval.rerank_metrics import rerank_uplift
from andromeda.eval.retrieval_metrics import metrics_for_ranked_ids


def test_metrics_for_ranked_ids_binary_case() -> None:
    metrics = metrics_for_ranked_ids(
        ranked_ids=["C3", "C2", "C1"],
        relevant_ids={"C1"},
        target_id="C1",
        relevance_by_id={"C1": 1.0},
    )
    assert metrics.rank == 3
    assert metrics.mrr == 1.0 / 3.0
    assert metrics.hit_at_5 == 1.0
    assert metrics.hit_at_10 == 1.0
    assert metrics.hit_at_25 == 1.0
    assert metrics.precision_at_5 == 1.0 / 3.0
    assert metrics.precision_at_10 == 1.0 / 3.0
    assert metrics.precision_at_25 == 1.0 / 3.0
    assert metrics.recall_at_5 == 1.0
    assert metrics.recall_at_10 == 1.0
    assert metrics.recall_at_25 == 1.0


def test_rerank_uplift_reports_rank_improvement() -> None:
    pre = metrics_for_ranked_ids(
        ranked_ids=["C1", "C2", "C3"],
        relevant_ids={"C3"},
        target_id="C3",
        relevance_by_id={"C3": 1.0},
    )
    post = metrics_for_ranked_ids(
        ranked_ids=["C3", "C1", "C2"],
        relevant_ids={"C3"},
        target_id="C3",
        relevance_by_id={"C3": 1.0},
    )
    uplift = rerank_uplift(pre=pre, post=post)
    assert uplift["rank_shift"] == 2
    assert uplift["win"] == 1
    assert uplift["loss"] == 0
    assert uplift["delta_mrr"] > 0
    assert uplift["delta_precision_at_5"] >= 0
    assert uplift["delta_recall_at_5"] >= 0


def test_citation_support_summary_counts_supported_and_unsupported() -> None:
    summary = citation_support_summary(
        cited_chunk_ids=["A", "B", "C"],
        available_chunk_ids=["A", "C", "D"],
    )
    assert summary.citation_count == 3
    assert summary.supported_citation_count == 2
    assert summary.unsupported_citation_count == 1
    assert summary.supported_rate == 2 / 3
