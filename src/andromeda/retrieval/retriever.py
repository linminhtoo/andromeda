from __future__ import annotations

from datetime import date
from typing import Callable, Iterable, Protocol

from loguru import logger
from sentence_transformers import CrossEncoder

from andromeda.dataclasses import DocChunk, ScoredChunk
from andromeda.retrieval.db import (
    ChunkRecord,
    DocumentRecord,
    HybridSearchRow,
    IngestedCompanyRow,
    PostgresDB,
    RetrievalFilters,
    SparseSearchMethod,
    normalize_iso_date,
)
from andromeda.llm.clients import LLMClient
from andromeda.processing.metadata_models import ChunkMetadata, chunk_metadata_from_value


class EmbeddingError(RuntimeError):
    """
    Raised when dense embedding generation fails.
    """


class CandidateTextProvider(Protocol):
    """
    Interface for supplying reranker candidate text.
    """

    def __call__(self, chunk: DocChunk) -> str: ...


class PostgresHybridRetriever:
    """
    PostgreSQL-backed hybrid retriever (pgvector + configurable sparse ranking).

    Parameters
    ----------
    llm_client : LLMClient
        Client used for dense embedding generation.
    dsn : str
        PostgreSQL connection string.
    alpha : float, optional
        Dense score weight in weighted RRF fusion.
    rrf_k : int, optional
        Reciprocal-rank offset constant.
    context_builder : Callable[[DocChunk], str] | None, optional
        Optional callback for generating contextual text at index time.
    retrieval_text_key : str, optional
        Metadata key containing enriched indexing text.
    retrieval_context_key : str, optional
        Metadata key used for stored contextual text.
    postgres_schema : str | None, optional
        Optional PostgreSQL schema name used for table/index isolation.
    sparse_search_method : SparseSearchMethod, optional
        Sparse ranking strategy (`bm25` or `fts`).
    ann_hnsw_m : int | None, optional
        Optional HNSW `m` index build parameter.
    ann_hnsw_ef_construction : int | None, optional
        Optional HNSW `ef_construction` index build parameter.
    auto_init_schema : bool, optional
        Whether to ensure schema/indexes on initialization.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        dsn: str,
        *,
        alpha: float = 0.6,
        rrf_k: int = 60,
        context_builder: Callable[[DocChunk], str] | None = None,
        retrieval_text_key: str = "retrieval_text",
        retrieval_context_key: str = "retrieval_context",
        postgres_schema: str | None = None,
        sparse_search_method: SparseSearchMethod = "bm25",
        ann_hnsw_m: int | None = None,
        ann_hnsw_ef_construction: int | None = None,
        auto_init_schema: bool = True,
    ):
        self.llm = llm_client
        self.alpha = float(alpha)
        self.rrf_k = int(rrf_k)
        self.context_builder = context_builder
        self.retrieval_text_key = retrieval_text_key
        self.retrieval_context_key = retrieval_context_key
        self.db = PostgresDB(
            dsn,
            postgres_schema=postgres_schema,
            sparse_search_method=sparse_search_method,
            ann_hnsw_m=ann_hnsw_m,
            ann_hnsw_ef_construction=ann_hnsw_ef_construction,
        )

        if auto_init_schema:
            self.db.ensure_schema()
            logger.info("Initialized PostgreSQL schema for retrieval (dsn={})", self.db.redacted_dsn())

    @staticmethod
    def chunk_index_from_id(chunk_id: str) -> int:
        """
        Parse a stable integer chunk index from a chunk ID suffix.

        Examples
        --------
        `abc_12` -> 12
        `abc` -> 0
        """

        head, sep, tail = chunk_id.rpartition("_")
        if sep and head and tail.isdigit():
            return int(tail)
        return 0

    def build_filters(
        self, *, tickers: Iterable[str] | None, filing_date_from: str | date | None, filing_date_to: str | date | None
    ) -> RetrievalFilters:
        """
        Build validated retrieval filters.
        """

        normalized_tickers = tuple(ticker.strip().upper() for ticker in (tickers or ()) if ticker and ticker.strip())
        return RetrievalFilters(
            tickers=normalized_tickers,
            filing_date_from=normalize_iso_date(filing_date_from),
            filing_date_to=normalize_iso_date(filing_date_to),
        )

    def text_for_embedding(self, chunk: DocChunk, *, use_builder: bool) -> tuple[str, str | None]:
        """
        Resolve text passed to the embedding model.
        """

        _retrieval_text, retrieval_context, embedding_text = self.resolve_retrieval_content(
            chunk, use_builder=use_builder
        )
        return embedding_text, retrieval_context

    def resolve_retrieval_content(self, chunk: DocChunk, *, use_builder: bool) -> tuple[str, str | None, str]:
        """
        Resolve retrieval fields for storage and embeddings.

        Returns
        -------
        tuple[str, str | None, str]
            `(retrieval_text, retrieval_context, embedding_text)`.
        """

        metadata = chunk_metadata_from_value(chunk.metadata)
        retrieval_text = chunk.text
        if self.retrieval_text_key == "retrieval_text" and metadata.retrieval_text:
            retrieval_text = metadata.retrieval_text.strip()
        elif self.retrieval_text_key in metadata.extra:
            value = metadata.extra[self.retrieval_text_key]
            if isinstance(value, str) and value.strip():
                retrieval_text = value.strip()
            elif value:
                retrieval_text = str(value).strip()

        retrieval_context = None
        if self.retrieval_context_key == "retrieval_context":
            retrieval_context = metadata.retrieval_context.strip() if metadata.retrieval_context else None
        elif self.retrieval_context_key in metadata.extra:
            value = metadata.extra[self.retrieval_context_key]
            if isinstance(value, str) and value.strip():
                retrieval_context = value.strip()
            elif value:
                retrieval_context = str(value).strip()

        if use_builder and self.context_builder is not None:
            built = self.context_builder(chunk).strip()
            if built:
                retrieval_context = built

        if retrieval_context:
            return retrieval_text, retrieval_context, f"Context:\n{retrieval_context}\n\nChunk:\n{retrieval_text}"
        return retrieval_text, None, retrieval_text

    def text_for_rerank(self, chunk: DocChunk) -> str:
        """
        Candidate text used by cross-encoder reranker.
        """

        _retrieval_text, _retrieval_context, embedding_text = self.resolve_retrieval_content(chunk, use_builder=False)
        return embedding_text

    def document_record_from_chunk(self, chunk: DocChunk) -> DocumentRecord:
        """
        Build a `DocumentRecord` from chunk metadata.
        """

        metadata = chunk_metadata_from_value(chunk.metadata)
        doc_meta = metadata.doc

        return DocumentRecord(
            doc_id=chunk.doc_id,
            source=chunk.source,
            source_relpath=None,
            ticker=(doc_meta.ticker.strip().upper() if doc_meta and doc_meta.ticker else None),
            company=(doc_meta.company.strip() if doc_meta and doc_meta.company else None),
            cik=(doc_meta.cik.strip() if doc_meta and doc_meta.cik else None),
            accession=(doc_meta.accession.strip() if doc_meta and doc_meta.accession else None),
            filing_type=(doc_meta.filing_type.strip() if doc_meta and doc_meta.filing_type else None),
            filing_date=normalize_iso_date(doc_meta.filing_date if doc_meta else None),
            period_end_date=normalize_iso_date(doc_meta.period_end_date if doc_meta else None),
            filing_quarter=(doc_meta.filing_quarter.strip() if doc_meta and doc_meta.filing_quarter else None),
            metadata=(doc_meta.to_dict() if doc_meta else {}),
        )

    def chunk_record_from_embedding(
        self, chunk: DocChunk, *, embedding: list[float], retrieval_text: str, retrieval_context: str | None
    ) -> ChunkRecord:
        """
        Build a `ChunkRecord` from a chunk and computed embedding state.
        """

        metadata_model = ChunkMetadata.from_value(chunk.metadata)
        metadata = metadata_model.to_dict()
        metadata[self.retrieval_text_key] = retrieval_text
        if retrieval_context:
            metadata[self.retrieval_context_key] = retrieval_context

        return ChunkRecord(
            chunk_id=chunk.id,
            doc_id=chunk.doc_id,
            chunk_index=self.chunk_index_from_id(chunk.id),
            page_no=chunk.page_no,
            headings=list(chunk.headings or []),
            source=chunk.source,
            text=chunk.text,
            retrieval_text=retrieval_text,
            retrieval_context=retrieval_context,
            metadata=metadata,
            embedding=embedding,
        )

    def upsert_documents(self, documents: list[DocumentRecord]) -> None:
        """
        Upsert document rows to PostgreSQL.
        """

        self.db.upsert_documents(documents)

    def existing_chunk_ids(self, chunk_ids: Iterable[str]) -> set[str]:
        """
        Return the subset of chunk IDs already stored.
        """

        return self.db.existing_chunk_ids(chunk_ids)

    def list_ingested_companies(self) -> list[IngestedCompanyRow]:
        """
        Return indexed ticker/company rows from PostgreSQL corpus metadata.
        """

        return self.db.list_ingested_companies()

    def index(self, chunks: list[DocChunk], *, rebuild_bm25: bool = True) -> None:
        """
        Index chunk rows into PostgreSQL.

        Parameters
        ----------
        chunks : list[DocChunk]
            Chunks to upsert.
        rebuild_bm25 : bool, optional
            Kept for API compatibility; PostgreSQL FTS does not require rebuild.
        """

        _ = rebuild_bm25
        if not chunks:
            return

        documents_by_id: dict[str, DocumentRecord] = {}
        retrieval_texts: list[str] = []
        retrieval_contexts: list[str | None] = []
        embedding_texts: list[str] = []

        for chunk in chunks:
            documents_by_id.setdefault(chunk.doc_id, self.document_record_from_chunk(chunk))
            retrieval_text, retrieval_context, embedding_text = self.resolve_retrieval_content(chunk, use_builder=True)
            retrieval_texts.append(retrieval_text)
            retrieval_contexts.append(retrieval_context)
            embedding_texts.append(embedding_text)

        try:
            embeddings = self.llm.embed_texts(embedding_texts)
        except Exception as exc:  # noqa: BLE001
            raise EmbeddingError(f"Failed to embed {len(embedding_texts)} chunk texts") from exc

        self.upsert_documents(list(documents_by_id.values()))

        rows: list[ChunkRecord] = []
        for idx, chunk in enumerate(chunks):
            rows.append(
                self.chunk_record_from_embedding(
                    chunk,
                    embedding=[float(v) for v in embeddings[idx].tolist()],
                    retrieval_text=retrieval_texts[idx],
                    retrieval_context=retrieval_contexts[idx],
                )
            )

        self.db.upsert_chunks(rows)

    def scored_chunk_from_row(self, row: HybridSearchRow) -> ScoredChunk:
        """
        Convert a retrieved SQL row to `ScoredChunk`.
        """

        metadata = dict(row.metadata)
        if self.retrieval_text_key not in metadata:
            metadata[self.retrieval_text_key] = row.retrieval_text
        if row.retrieval_context and self.retrieval_context_key not in metadata:
            metadata[self.retrieval_context_key] = row.retrieval_context

        chunk = DocChunk(
            id=row.chunk_id,
            doc_id=row.doc_id,
            text=row.text,
            page_no=row.page_no,
            headings=list(row.headings),
            source=row.source,
            metadata=metadata,
        )
        return ScoredChunk(chunk=chunk, score=row.score, source="hybrid")

    def retrieve_hybrid(
        self,
        query: str,
        top_k_semantic: int = 20,
        top_k_bm25: int = 20,
        top_k_final: int = 20,
        alpha: float | None = None,
        *,
        filters: RetrievalFilters | None = None,
    ) -> list[ScoredChunk]:
        """
        Retrieve chunks using PostgreSQL dense + sparse hybrid ranking.

        Parameters
        ----------
        query : str
            Input query text.
        top_k_semantic : int, optional
            Dense candidate count.
        top_k_bm25 : int, optional
            Sparse candidate count.
        top_k_final : int, optional
            Final fused result count.
        alpha : float | None, optional
            Dense score weight override.
        filters : RetrievalFilters | None, optional
            Optional pre-retrieval constraints.

        Returns
        -------
        list[ScoredChunk]
            Retrieved scored chunks.
        """

        try:
            query_vector = self.llm.embed_texts([query])[0].tolist()
        except Exception as exc:  # noqa: BLE001
            raise EmbeddingError("Failed to embed query text for retrieval") from exc

        rows = self.db.hybrid_search(
            query_text=query,
            query_vector=query_vector,
            top_k_semantic=top_k_semantic,
            top_k_sparse=top_k_bm25,
            top_k_final=top_k_final,
            alpha=float(alpha if alpha is not None else self.alpha),
            rrf_k=self.rrf_k,
            filters=filters,
        )

        return [self.scored_chunk_from_row(row) for row in rows]


class CrossEncoderReranker:
    """
    Cross-encoder reranker using SentenceTransformers.

    Parameters
    ----------
    model_name : str, optional
        Pretrained cross-encoder model name.
        Defaults to "cross-encoder/ms-marco-MiniLM-L-6-v2".
    """

    def __init__(
        self,
        model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
        *,
        candidate_text_provider: CandidateTextProvider | None = None,
    ):
        self.model = CrossEncoder(model_name, trust_remote_code=True)
        self.candidate_text_provider = candidate_text_provider

    def rerank(
        self,
        query: str,
        candidates: list[ScoredChunk],
        top_k: int = 10,
        *,
        candidate_text_provider: CandidateTextProvider | None = None,
    ) -> list[ScoredChunk]:
        """
        Rerank chunk candidates by cross-encoder relevance.
        """

        if not candidates:
            return []

        provider = candidate_text_provider or self.candidate_text_provider
        if provider is None:
            pairs = [(query, candidate.chunk.text) for candidate in candidates]
        else:
            pairs = [(query, provider(candidate.chunk)) for candidate in candidates]

        scores = self.model.predict(pairs).tolist()
        rescored: list[ScoredChunk] = []
        for candidate, score in zip(candidates, scores):
            rescored.append(ScoredChunk(chunk=candidate.chunk, score=float(score), source="reranker"))

        rescored.sort(key=lambda item: item.score, reverse=True)
        return rescored[:top_k]


class NoopReranker:
    """
    Reranker that preserves retrieval ordering by score.
    """

    def rerank(
        self,
        query: str,
        candidates: list[ScoredChunk],
        top_k: int = 10,
        *,
        candidate_text_provider: CandidateTextProvider | None = None,
    ) -> list[ScoredChunk]:
        """
        Return top-k candidates sorted by existing score.
        """

        _ = query
        _ = candidate_text_provider
        ordered = list(candidates)
        ordered.sort(key=lambda item: item.score, reverse=True)
        return ordered[:top_k]
