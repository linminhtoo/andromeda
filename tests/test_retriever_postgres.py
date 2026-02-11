from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np

from finrag.dataclasses import DocChunk
from finrag.db import ChunkRecord, DocumentRecord, HybridSearchRow, RetrievalFilters
from finrag.retriever import PostgresHybridRetriever
from tests.fakes import RecordingLLM


@dataclass
class FakeDB:
    documents: list[DocumentRecord]
    chunks: list[ChunkRecord]
    query_rows: list[HybridSearchRow]
    last_hybrid_args: dict[str, Any] | None = None

    def upsert_documents(self, documents: list[DocumentRecord]) -> None:
        self.documents.extend(documents)

    def upsert_chunks(self, chunks: list[ChunkRecord]) -> None:
        self.chunks.extend(chunks)

    def existing_chunk_ids(self, chunk_ids) -> set[str]:
        existing = {row.chunk_id for row in self.chunks}
        return {chunk_id for chunk_id in chunk_ids if chunk_id in existing}

    def hybrid_search(self, **kwargs) -> list[HybridSearchRow]:
        self.last_hybrid_args = kwargs
        return list(self.query_rows)


def test_index_stores_retrieval_text_and_context_separately() -> None:
    embedded_inputs: list[str] = []

    def embed_fn(texts: list[str]) -> np.ndarray:
        embedded_inputs.extend(texts)
        return np.asarray([[float(len(text))] for text in texts], dtype=np.float32)

    llm = RecordingLLM(embed_fn=embed_fn)
    retriever = PostgresHybridRetriever(
        llm_client=llm, dsn="postgresql://user:pass@localhost/db", auto_init_schema=False
    )
    fake_db = FakeDB(documents=[], chunks=[], query_rows=[])
    retriever.db = fake_db

    chunk = DocChunk(
        id="doc_0",
        doc_id="doc",
        text="raw text",
        page_no=1,
        headings=["Risk Factors"],
        source="AAPL_000012345678901234_10-Q_2024-08-01.md",
        metadata={
            "retrieval_text": "Company: Apple\nSection: Risk Factors\n\nraw text",
            "retrieval_context": "Previous chunk discusses gross margin trends.",
            "doc": {"ticker": "aapl", "filing_date": "2024-08-01"},
        },
    )

    retriever.index([chunk])

    assert len(fake_db.documents) == 1
    assert len(fake_db.chunks) == 1

    stored = fake_db.chunks[0]
    assert stored.retrieval_text == "Company: Apple\nSection: Risk Factors\n\nraw text"
    assert stored.retrieval_context == "Previous chunk discusses gross margin trends."
    assert embedded_inputs == [
        "Company: Apple\nSection: Risk Factors\n\nraw text\n\nContext: Previous chunk discusses gross margin trends."
    ]
    assert stored.metadata["retrieval_text"] == stored.retrieval_text
    assert stored.metadata["retrieval_context"] == stored.retrieval_context


def test_retrieve_hybrid_passes_filters_and_maps_rows() -> None:
    llm = RecordingLLM(embed_fn=lambda texts: np.asarray([[1.0, 2.0] for _ in texts], dtype=np.float32))
    retriever = PostgresHybridRetriever(
        llm_client=llm, dsn="postgresql://user:pass@localhost/db", auto_init_schema=False
    )
    fake_db = FakeDB(
        documents=[],
        chunks=[],
        query_rows=[
            HybridSearchRow(
                score=0.91,
                chunk_id="chunk_1",
                doc_id="doc_1",
                page_no=4,
                headings=["Management Discussion"],
                source="NVDA_000012345678901234_10-Q_2024-11-20.md",
                text="Original chunk text",
                retrieval_text="Company: NVIDIA\nSection: Management Discussion\n\nOriginal chunk text",
                retrieval_context="Neighboring chunks discuss data center demand.",
                metadata={"doc": {"ticker": "NVDA"}},
            )
        ],
    )
    retriever.db = fake_db

    filters = retriever.build_filters(
        tickers=[" nvda ", "AAPL", "nvda"], filing_date_from=date(2024, 1, 1), filing_date_to="2024-12-31"
    )
    results = retriever.retrieve_hybrid(
        "How did data center revenue trend?", top_k_semantic=8, top_k_bm25=10, top_k_final=5, filters=filters
    )

    assert len(results) == 1
    assert results[0].chunk.id == "chunk_1"
    assert results[0].score == 0.91
    assert results[0].chunk.metadata and results[0].chunk.metadata["retrieval_text"].startswith("Company: NVIDIA")
    assert results[0].chunk.metadata["retrieval_context"] == "Neighboring chunks discuss data center demand."

    assert fake_db.last_hybrid_args is not None
    call_filters = fake_db.last_hybrid_args["filters"]
    assert isinstance(call_filters, RetrievalFilters)
    assert call_filters.normalized_tickers() == ("NVDA", "AAPL")
    assert call_filters.filing_date_from == date(2024, 1, 1)
    assert call_filters.filing_date_to == date(2024, 12, 31)
