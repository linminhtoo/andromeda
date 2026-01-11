from __future__ import annotations

from finrag.eval.generation import (
    _OPEN_ENDED_TEMPLATES,
    generate_comparison_queries,
    generate_distractor_queries,
    generate_open_ended_queries,
)


def test_open_ended_uses_multiple_unique_templates_per_pair() -> None:
    docs = [
        {"ticker": "AAA", "year": 2020, "company": "Acme Corp"},
        {"ticker": "BBB", "year": 2021, "company": "Beta Inc"},
    ]
    n = 6
    out = generate_open_ended_queries(docs, n=n, seed=123)
    assert len(out) == n

    counts: dict[tuple[str | None, int | None], int] = {}
    tmpl_ids: dict[tuple[str | None, int | None], set[int]] = {}
    for q in out:
        assert q.open_ended is not None
        key = (q.open_ended.target_ticker, q.open_ended.target_year)
        counts[key] = counts.get(key, 0) + 1
        tmpl_id = q.generator.get("template_id")
        assert isinstance(tmpl_id, int)
        tmpl_ids.setdefault(key, set()).add(tmpl_id)

    for key, count in counts.items():
        assert len(tmpl_ids[key]) == count


def test_open_ended_caps_at_all_pair_template_combos() -> None:
    docs = [
        {"ticker": "AAA", "year": 2020, "company": "Acme Corp"},
        {"ticker": "BBB", "year": 2021, "company": "Beta Inc"},
    ]
    out = generate_open_ended_queries(docs, n=999, seed=0)
    assert len(out) == 2 * len(_OPEN_ENDED_TEMPLATES)


def test_distractor_uses_multiple_unique_main_templates_per_pair() -> None:
    docs = [
        {"ticker": "AAA", "year": 2020, "company": "Acme Corp"},
        {"ticker": "BBB", "year": 2021, "company": "Beta Inc"},
    ]
    n = 7
    out = generate_distractor_queries(docs, n=n, seed=456)
    assert len(out) == n

    counts: dict[tuple[int | None, str | None], int] = {}
    tmpl_ids: dict[tuple[int | None, str | None], set[int]] = {}
    for q in out:
        assert q.distractor is not None
        assert q.distractor.target_tickers
        key = (q.distractor.target_year, q.distractor.target_tickers[0])
        counts[key] = counts.get(key, 0) + 1
        tmpl_id = q.generator.get("main_template_id")
        assert isinstance(tmpl_id, int)
        tmpl_ids.setdefault(key, set()).add(tmpl_id)

    for key, count in counts.items():
        assert len(tmpl_ids[key]) == count


def test_comparison_can_generate_multiple_per_year() -> None:
    docs = [
        {"ticker": "AAA", "year": 2022, "company": "Acme Corp"},
        {"ticker": "BBB", "year": 2022, "company": "Beta Inc"},
        {"ticker": "CCC", "year": 2022, "company": "Charlie LLC"},
    ]
    out = generate_comparison_queries(docs, n=5, seed=1, min_companies=2, max_companies=2)
    assert len(out) == 5
    assert len({q.question for q in out}) == len(out)
