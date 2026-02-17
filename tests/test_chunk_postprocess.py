from __future__ import annotations

from andromeda.processing.chunk_postprocess import (
    DocumentContextPostprocessor,
    HeuristicSummaryPostprocessor,
    SectionLinkPostprocessor,
    StaticTickerCompanyNameResolver,
)
from andromeda.dataclasses import DocChunk


def test_section_link_postprocessor_adds_global_and_section_links() -> None:
    chunks = [
        DocChunk(id="c1", doc_id="d", text="t1", page_no=None, headings=["A"], source="s"),
        DocChunk(id="c2", doc_id="d", text="t2", page_no=None, headings=["A"], source="s"),
        DocChunk(id="c3", doc_id="d", text="t3", page_no=None, headings=["B"], source="s"),
    ]

    pp = SectionLinkPostprocessor(
        neighbor_window=1, include_section_chunk_ids=True, include_section_related_ids=True, max_related_ids=10
    )
    out = pp.process(chunks)
    assert out is chunks

    m1 = chunks[0].metadata or {}
    m2 = chunks[1].metadata or {}
    m3 = chunks[2].metadata or {}

    assert m1["prev_chunk_id"] is None
    assert m1["next_chunk_id"] == "c2"
    assert m2["prev_chunk_id"] == "c1"
    assert m2["next_chunk_id"] == "c3"
    assert m3["prev_chunk_id"] == "c2"
    assert m3["next_chunk_id"] is None

    assert isinstance(m1["section_id"], str) and len(m1["section_id"]) == 16
    assert m1["section_id"] == m2["section_id"]
    assert m1["section_id"] != m3["section_id"]

    assert m1["section_index"] == 0
    assert m2["section_index"] == 1
    assert m1["section_size"] == 2
    assert m2["section_size"] == 2

    assert m1["section_chunk_ids"] == ["c1", "c2"]
    assert m2["section_chunk_ids"] == ["c1", "c2"]
    assert m1["related_chunk_ids"] == ["c2"]
    assert m2["related_chunk_ids"] == ["c1"]

    assert m1["section_neighbor_chunk_ids"] == ["c2"]
    assert m2["section_neighbor_chunk_ids"] == ["c1"]


def test_document_context_postprocessor_extracts_from_filename_and_text() -> None:
    resolver = StaticTickerCompanyNameResolver({"AAPL": "Apple Inc"})
    pp = DocumentContextPostprocessor(company_name_resolver=resolver)

    src = "AAPL_000012345678901234_10-Q_2024-08-01.md"
    chunks = [
        DocChunk(
            id="c1",
            doc_id="doc1",
            text="For the quarterly period ended June 30, 2024 we did stuff.",
            page_no=None,
            headings=["APPLE INC."],
            source=src,
            metadata={},
        ),
        DocChunk(
            id="c2", doc_id="doc1", text="More text", page_no=None, headings=["APPLE INC."], source=src, metadata={}
        ),
    ]

    pp.process(chunks)

    for ch in chunks:
        doc = (ch.metadata or {}).get("doc")
        assert isinstance(doc, dict)
        assert doc["ticker"] == "AAPL"
        assert doc["accession"] == "000012345678901234"
        assert doc["cik"] == "0000123456"
        assert doc["filing_type"] == "10-Q"
        assert doc["filing_date"] == "2024-08-01"
        assert doc["company"] == "Apple Inc"
        assert doc["period_end_date"] == "2024-06-30"
        assert doc["filing_quarter"] == "2024Q2"
        assert doc["filing_quarter_basis"] == "period_end_date"


def test_heuristic_summary_postprocessor_builds_retrieval_text_for_tables() -> None:
    pp = HeuristicSummaryPostprocessor()
    chunks = [
        DocChunk(
            id="c1",
            doc_id="d",
            text="| A | B |\n|---|---|\n| 1 | 2 |",
            page_no=3,
            headings=["Some Section"],
            source="s",
            metadata={
                "block_type": "table",
                "doc": {
                    "company": "Apple Inc",
                    "ticker": "AAPL",
                    "filing_type": "10-Q",
                    "filing_date": "2024-08-01",
                    "period_end_date": "2024-06-30",
                    "filing_quarter": "2024Q2",
                },
            },
        )
    ]

    pp.process(chunks)
    meta = chunks[0].metadata or {}
    assert isinstance(meta.get("summary"), str) and meta["summary"]
    assert "Columns:" in meta["summary"]

    retrieval_text = meta.get("retrieval_text")
    assert isinstance(retrieval_text, str)
    assert retrieval_text.startswith("Company: Apple Inc")
    assert "\nTicker: AAPL" in retrieval_text
    assert "Filing: 10-Q, filed 2024-08-01, period ended 2024-06-30" in retrieval_text
    assert "\nFiling quarter: 2024Q2" in retrieval_text
    assert "\nSection: Some Section" in retrieval_text
    assert "\nPage: 3" in retrieval_text
    assert "\n\n| A | B |" in retrieval_text
