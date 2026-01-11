from __future__ import annotations

import math

from finrag.eval.metrics import (
    best_numeric_match,
    cited_doc_ids,
    coverage_at_k,
    extract_numbers,
    keyword_coverage,
    mrr,
    recall_at_k,
)


def test_rank_metrics_nan_when_no_relevant() -> None:
    assert math.isnan(recall_at_k(["a"], set(), 1))
    assert math.isnan(mrr(["a"], set()))
    assert math.isnan(coverage_at_k(["a"], set(), 1))


def test_rank_metrics_values() -> None:
    assert recall_at_k(["x", "y"], {"y"}, 1) == 0.0
    assert recall_at_k(["x", "y"], {"y"}, 2) == 1.0
    assert mrr(["x", "y"], {"y"}) == 0.5
    assert coverage_at_k(["x", "y", "z"], {"y", "z"}, 2) == 0.5


def test_extract_numbers_parses_currency_commas_and_parens() -> None:
    nums = extract_numbers("Revenue was $1,234.50; loss was (2,000).")
    assert 1234.5 in nums
    assert -2000.0 in nums


def test_best_numeric_match_handles_scale_hints() -> None:
    out = best_numeric_match("Revenue was 10 million USD.", expected_value=10, expected_scale="millions")
    assert out["matched"] is True


def test_cited_doc_ids_parses_inline_citations() -> None:
    assert cited_doc_ids("hello [doc=AAPL] world [doc=MSFT page=2]") == {"AAPL", "MSFT"}


def test_keyword_coverage_simple() -> None:
    score = keyword_coverage("We discuss revenue and margins.", ["Revenue increased a lot.", "Cash flow was strong."])
    assert score == 0.5

