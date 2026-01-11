from __future__ import annotations

import pytest

from finrag.dataclasses import DocChunk
from finrag.retriever import EmbeddingError, QdrantHybridRetriever
from tests.fakes import RecordingLLM, keyword_count_embed


def test_qdrant_hybrid_retriever_index_and_retrieve(tmp_path) -> None:
    llm = RecordingLLM(embed_fn=lambda texts: keyword_count_embed(texts, keywords=["revenue", "profit"]))
    r = QdrantHybridRetriever(llm_client=llm, storage_path=":memory:", collection_name="t", load_existing=False)

    chunks = [
        DocChunk(
            id="c_rev", doc_id="DOCREV", text="Revenue increased this quarter.", page_no=1, headings=[], source="s"
        ),
        DocChunk(id="c_prof", doc_id="DOCPROF", text="Profit decreased slightly.", page_no=1, headings=[], source="s"),
    ]
    r.index(chunks)

    assert r.existing_chunk_ids(["c_rev", "missing"]) == {"c_rev"}

    hits = r.retrieve_hybrid("revenue", top_k_semantic=5, top_k_bm25=5, top_k_final=2)
    assert hits
    assert hits[0].chunk.id == "c_rev"


def test_qdrant_hybrid_retriever_wraps_embedding_failures() -> None:
    class BadLLM(RecordingLLM):
        def embed_texts(self, texts):
            raise RuntimeError("boom")

    r = QdrantHybridRetriever(llm_client=BadLLM(), storage_path=":memory:", collection_name="t2", load_existing=False)
    with pytest.raises(EmbeddingError, match="Failed to embed"):
        r.index([DocChunk(id="c1", doc_id="d", text="x", page_no=None, headings=[], source="s")])
