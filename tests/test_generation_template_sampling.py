from __future__ import annotations

from collections import defaultdict

from finrag.eval.generation import (
    CompanyYearTarget,
    _OPEN_ENDED_TEMPLATES,
    generate_comparison_queries,
    generate_distractor_queries,
    generate_open_ended_queries,
)


def test_open_ended_uses_multiple_unique_templates_per_pair() -> None:
    docs = [
        CompanyYearTarget(ticker="AAA", year=2020, company="Acme Corp"),
        CompanyYearTarget(ticker="BBB", year=2021, company="Beta Inc"),
    ]
    n = 6
    out = generate_open_ended_queries(docs, n=n, seed=123)
    assert len(out) == n

    counts: defaultdict[tuple[str | None, int | None], int] = defaultdict(int)
    tmpl_ids: defaultdict[tuple[str | None, int | None], set[int]] = defaultdict(set)
    for q in out:
        assert q.open_ended is not None
        key = (q.open_ended.target_ticker, q.open_ended.target_year)
        counts[key] += 1
        assert "template_id" in q.generator
        tmpl_id = q.generator["template_id"]
        assert isinstance(tmpl_id, int)
        tmpl_ids[key].add(tmpl_id)

    for key, count in counts.items():
        assert len(tmpl_ids[key]) == count


def test_open_ended_caps_at_all_pair_template_combos() -> None:
    docs = [
        CompanyYearTarget(ticker="AAA", year=2020, company="Acme Corp"),
        CompanyYearTarget(ticker="BBB", year=2021, company="Beta Inc"),
    ]
    out = generate_open_ended_queries(docs, n=999, seed=0)
    assert len(out) == 2 * len(_OPEN_ENDED_TEMPLATES)


def test_distractor_uses_multiple_unique_main_templates_per_pair() -> None:
    docs = [
        CompanyYearTarget(ticker="AAA", year=2020, company="Acme Corp"),
        CompanyYearTarget(ticker="BBB", year=2021, company="Beta Inc"),
    ]
    n = 7
    out = generate_distractor_queries(docs, n=n, seed=456)
    assert len(out) == n

    counts: defaultdict[tuple[int | None, str | None], int] = defaultdict(int)
    tmpl_ids: defaultdict[tuple[int | None, str | None], set[int]] = defaultdict(set)
    for q in out:
        assert q.distractor is not None
        assert q.distractor.target_tickers
        key = (q.distractor.target_year, q.distractor.target_tickers[0])
        counts[key] += 1
        assert "main_template_id" in q.generator
        tmpl_id = q.generator["main_template_id"]
        assert isinstance(tmpl_id, int)
        tmpl_ids[key].add(tmpl_id)

    for key, count in counts.items():
        assert len(tmpl_ids[key]) == count


def test_comparison_can_generate_multiple_per_year() -> None:
    docs = [
        CompanyYearTarget(ticker="AAA", year=2022, company="Acme Corp"),
        CompanyYearTarget(ticker="BBB", year=2022, company="Beta Inc"),
        CompanyYearTarget(ticker="CCC", year=2022, company="Charlie LLC"),
    ]
    out = generate_comparison_queries(docs, n=5, seed=1, min_companies=2, max_companies=2)
    assert len(out) == 5
    assert len({q.question for q in out}) == len(out)
