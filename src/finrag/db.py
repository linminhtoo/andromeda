from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable, Literal, LiteralString, Sequence

import psycopg
from psycopg.rows import dict_row
from psycopg.sql import SQL, Composable, Identifier, Literal as SqlLiteral
from psycopg.types.json import Jsonb


SparseSearchMethod = Literal["bm25", "fts"]


@dataclass(frozen=True)
class RetrievalFilters:
    """
    Retrieval constraints applied before dense/sparse ranking.

    Attributes
    ----------
    tickers : tuple[str, ...]
        Optional list of ticker symbols to restrict retrieval.
    filing_date_from : date | None
        Optional inclusive filing date lower bound.
    filing_date_to : date | None
        Optional inclusive filing date upper bound.
    """

    tickers: tuple[str, ...] = ()
    filing_date_from: date | None = None
    filing_date_to: date | None = None

    def normalized_tickers(self) -> tuple[str, ...]:
        """
        Return uppercase tickers with stable order and duplicates removed.
        """

        unique: dict[str, None] = {}
        for ticker in self.tickers:
            value = ticker.strip().upper()
            if value:
                unique[value] = None
        return tuple(unique.keys())


@dataclass(frozen=True)
class DocumentRecord:
    """
    Normalized document row persisted in PostgreSQL.
    """

    doc_id: str
    source: str
    source_relpath: str | None
    ticker: str | None
    company: str | None
    cik: str | None
    accession: str | None
    filing_type: str | None
    filing_date: date | None
    period_end_date: date | None
    filing_quarter: str | None
    metadata: dict[str, Any]


@dataclass(frozen=True)
class ChunkRecord:
    """
    Chunk row persisted in PostgreSQL.
    """

    chunk_id: str
    doc_id: str
    chunk_index: int
    page_no: int | None
    headings: list[str]
    source: str
    text: str
    retrieval_text: str
    retrieval_context: str | None
    metadata: dict[str, Any]
    embedding: Sequence[float]


@dataclass(frozen=True)
class HybridSearchRow:
    """
    Typed retrieval row returned by PostgreSQL hybrid search.
    """

    score: float
    chunk_id: str
    doc_id: str
    page_no: int | None
    headings: list[str]
    source: str
    text: str
    retrieval_text: str
    retrieval_context: str | None
    metadata: dict[str, Any]


@dataclass(frozen=True)
class IngestedCompanyRow:
    """
    Typed ticker/company row discovered from indexed documents.
    """

    ticker: str
    company: str | None


def normalize_iso_date(value: str | date | None) -> date | None:
    """
    Normalize a date-like value into `datetime.date`.

    Parameters
    ----------
    value : str | date | None
        ISO date string (`YYYY-MM-DD`) or a `date` object.

    Returns
    -------
    date | None
        Parsed date when valid, otherwise `None`.
    """

    if value is None:
        return None
    if isinstance(value, date):
        return value
    text = value.strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def vector_literal(values: Sequence[float]) -> str:
    """
    Convert a numeric vector to a PostgreSQL pgvector literal.

    Parameters
    ----------
    values : Sequence[float]
        Dense embedding values.

    Returns
    -------
    str
        Literal representation like `[0.1,0.2,...]`.
    """

    nums = [f"{float(v):.8f}" for v in values]
    return "[" + ",".join(nums) + "]"


class PostgresDB:
    """
    Lightweight PostgreSQL data access layer for corpus and retrieval.

    Parameters
    ----------
    dsn : str
        PostgreSQL connection string.
    """

    def __init__(
        self,
        dsn: str,
        postgres_schema: str | None = None,
        sparse_search_method: SparseSearchMethod | str = "bm25",
        embedding_dim: int | None = None,
        ann_hnsw_m: int | None = None,
        ann_hnsw_ef_construction: int | None = None,
    ):
        self.dsn = dsn
        self.postgres_schema = self.normalize_schema_name(postgres_schema)
        self.sparse_search_method = self.normalize_sparse_search_method(sparse_search_method)
        self.embedding_dim = self.normalize_embedding_dim(embedding_dim)
        self.ann_hnsw_m = self.normalize_positive_int(ann_hnsw_m)
        self.ann_hnsw_ef_construction = self.normalize_positive_int(ann_hnsw_ef_construction)
        self._ann_index_ready = False
        self._sparse_method_verified_for_indexing = False
        self._sparse_method_verified_for_retrieval = False

    @staticmethod
    def normalize_sparse_search_method(value: SparseSearchMethod | str) -> SparseSearchMethod:
        """
        Return normalized sparse search method.
        """

        normalized = str(value).strip().lower()
        if normalized == "bm25":
            return "bm25"
        if normalized == "fts":
            return "fts"
        raise ValueError(f"Invalid sparse search method: {value!r}. Expected one of: bm25, fts.")

    def connect(self) -> psycopg.Connection[Any]:
        """
        Open a PostgreSQL connection.
        """

        conn = psycopg.connect(self.dsn)
        if self.postgres_schema is not None:
            with conn.cursor() as cur:
                cur.execute(SQL("CREATE SCHEMA IF NOT EXISTS {};").format(Identifier(self.postgres_schema)))
                cur.execute(SQL("SET search_path TO {}, public;").format(Identifier(self.postgres_schema)))
        return conn

    @staticmethod
    def normalize_schema_name(value: str | None) -> str | None:
        """
        Return a normalized schema name, else `None`.
        """

        if value is None:
            return None
        name = value.strip()
        if not name:
            return None
        return name

    @staticmethod
    def normalize_embedding_dim(value: int | None) -> int | None:
        """
        Return a positive embedding dimension, else `None`.
        """

        if value is None:
            return None
        dim = int(value)
        if dim <= 0:
            return None
        return dim

    @staticmethod
    def normalize_positive_int(value: int | None) -> int | None:
        """
        Return a positive integer, else `None`.
        """

        if value is None:
            return None
        out = int(value)
        if out <= 0:
            return None
        return out

    def resolve_embedding_dim(self) -> int | None:
        """
        Resolve the embedding dimension from config or existing rows.
        """

        if self.embedding_dim is not None:
            return self.embedding_dim

        with self.connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("SELECT vector_dims(embedding) AS dim FROM chunks LIMIT 1;")
                row = cur.fetchone()

        if row is None:
            return None
        dim_raw = row["dim"]
        if not isinstance(dim_raw, int) or dim_raw <= 0:
            return None
        self.embedding_dim = dim_raw
        return self.embedding_dim

    def ensure_ann_index(self, embedding_dim: int | None = None) -> None:
        """
        Ensure a HNSW ANN index exists for cosine similarity search.
        """

        if embedding_dim is not None:
            normalized_dim = self.normalize_embedding_dim(embedding_dim)
            if normalized_dim is None:
                raise ValueError(f"Invalid embedding dimension: {embedding_dim}")
            self.embedding_dim = normalized_dim

        dim = self.resolve_embedding_dim()
        if dim is None:
            return
        if self._ann_index_ready:
            return

        vector_type = SQL("vector({})").format(SqlLiteral(dim))

        hnsw_with_clauses: list[Composable] = []
        if self.ann_hnsw_m is not None:
            hnsw_with_clauses.append(SQL("m = {}").format(SqlLiteral(self.ann_hnsw_m)))
        if self.ann_hnsw_ef_construction is not None:
            hnsw_with_clauses.append(SQL("ef_construction = {}").format(SqlLiteral(self.ann_hnsw_ef_construction)))
        hnsw_with_sql = SQL("")
        if hnsw_with_clauses:
            hnsw_with_sql = SQL(" WITH (") + SQL(", ").join(hnsw_with_clauses) + SQL(")")

        hnsw_sql = SQL(
            """
            CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw
            ON chunks USING hnsw ((embedding::{vector_type}) vector_cosine_ops){hnsw_with_sql};
            """
        ).format(vector_type=vector_type, hnsw_with_sql=hnsw_with_sql)

        try:
            with self.connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(hnsw_sql)
            self._ann_index_ready = True
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Failed to create ANN index: {exc!r}") from exc

    def drop_ann_indexes(self) -> None:
        """
        Drop ANN indexes so they can be recreated with new parameters.
        """

        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("DROP INDEX IF EXISTS idx_chunks_embedding_hnsw;")
                # Keep cleanup for legacy deployments that previously created ivfflat indexes.
                cur.execute("DROP INDEX IF EXISTS idx_chunks_embedding_ivfflat;")
        self._ann_index_ready = False

    def ensure_schema(self) -> None:
        """
        Create required extensions, tables, and indexes.
        """

        statements: list[LiteralString] = [
            "CREATE EXTENSION IF NOT EXISTS vector;",
            """
            CREATE TABLE IF NOT EXISTS documents (
                doc_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                source_relpath TEXT,
                ticker TEXT,
                company TEXT,
                cik TEXT,
                accession TEXT,
                filing_type TEXT,
                filing_date DATE,
                period_end_date DATE,
                filing_quarter TEXT,
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS chunks (
                chunk_id TEXT PRIMARY KEY,
                doc_id TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
                chunk_index INTEGER NOT NULL,
                page_no INTEGER,
                headings TEXT[] NOT NULL DEFAULT '{}',
                source TEXT NOT NULL,
                text TEXT NOT NULL,
                retrieval_text TEXT NOT NULL,
                retrieval_context TEXT,
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                embedding vector NOT NULL,
                search_tsv TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', COALESCE(retrieval_text, ''))) STORED,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS retrieval_runtime_config (
                id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
                sparse_search_method TEXT NOT NULL CHECK (sparse_search_method IN ('bm25', 'fts')),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """,
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = 'chunks'
                      AND column_name = 'index_text'
                ) AND NOT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = 'chunks'
                      AND column_name = 'retrieval_text'
                ) THEN
                    ALTER TABLE chunks RENAME COLUMN index_text TO retrieval_text;
                END IF;
            END $$;
            """,
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = 'chunks'
                      AND column_name = 'context'
                ) AND NOT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = 'chunks'
                      AND column_name = 'retrieval_context'
                ) THEN
                    ALTER TABLE chunks RENAME COLUMN context TO retrieval_context;
                END IF;
            END $$;
            """,
            "CREATE INDEX IF NOT EXISTS idx_documents_ticker ON documents (ticker);",
            "CREATE INDEX IF NOT EXISTS idx_documents_filing_date ON documents (filing_date);",
            "CREATE INDEX IF NOT EXISTS idx_chunks_doc_id ON chunks (doc_id);",
        ]

        with self.connect() as conn:
            with conn.cursor() as cur:
                for statement in statements:
                    cur.execute(statement)

        self.ensure_sparse_indexes()
        # Optional ANN index creation is isolated from schema DDL.
        self.ensure_ann_index(self.embedding_dim)

    def ensure_sparse_indexes(self) -> None:
        """
        Ensure sparse retrieval indexes for configured method.
        """

        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("CREATE INDEX IF NOT EXISTS idx_chunks_search_tsv ON chunks USING GIN (search_tsv);")

                if self.sparse_search_method == "bm25":
                    try:
                        cur.execute("CREATE EXTENSION IF NOT EXISTS pg_textsearch;")
                        cur.execute(
                            """
                            CREATE INDEX IF NOT EXISTS idx_chunks_retrieval_text_bm25
                            ON chunks USING bm25(retrieval_text) WITH (text_config='english');
                            """
                        )
                    except Exception as exc:  # noqa: BLE001
                        raise RuntimeError(
                            "Failed to initialize BM25 sparse index. Install pg_textsearch or switch "
                            "to POSTGRES_SPARSE_SEARCH_METHOD=fts."
                        ) from exc

    def configured_sparse_search_method(self) -> SparseSearchMethod | None:
        """
        Return sparse method recorded for indexed corpus.
        """

        with self.connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("SELECT sparse_search_method FROM retrieval_runtime_config WHERE id = 1;")
                row = cur.fetchone()
        if row is None:
            return None
        return self.normalize_sparse_search_method(str(row["sparse_search_method"]))

    def ensure_sparse_method_for_indexing(self) -> None:
        """
        Persist and validate sparse method for index writes.
        """

        if self._sparse_method_verified_for_indexing:
            return

        configured = self.configured_sparse_search_method()
        if configured is None:
            with self.connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO retrieval_runtime_config (id, sparse_search_method, updated_at)
                        VALUES (1, %s, NOW())
                        ON CONFLICT (id) DO UPDATE
                        SET sparse_search_method = EXCLUDED.sparse_search_method,
                            updated_at = NOW();
                        """,
                        (self.sparse_search_method,),
                    )
            self._sparse_method_verified_for_indexing = True
            self._sparse_method_verified_for_retrieval = True
            return

        if configured != self.sparse_search_method:
            raise RuntimeError(
                "Sparse search method mismatch for indexing. "
                f"Indexed corpus method is '{configured}', but current configuration is "
                f"'{self.sparse_search_method}'. Use matching method for retrieval/indexing, or run a corpus reset "
                "before rebuilding with a different sparse method."
            )

        self._sparse_method_verified_for_indexing = True
        self._sparse_method_verified_for_retrieval = True

    def ensure_sparse_method_for_retrieval(self) -> None:
        """
        Validate sparse method compatibility before retrieval queries.
        """

        if self._sparse_method_verified_for_retrieval:
            return

        configured = self.configured_sparse_search_method()
        if configured is None:
            raise RuntimeError(
                "Sparse search method is not initialized for this schema. "
                "Run indexing first so retrieval can validate sparse method compatibility."
            )
        if configured != self.sparse_search_method:
            raise RuntimeError(
                "Sparse search method mismatch for retrieval. "
                f"Indexed corpus method is '{configured}', but current retrieval method is "
                f"'{self.sparse_search_method}'."
            )
        self._sparse_method_verified_for_retrieval = True

    def upsert_documents(self, documents: Sequence[DocumentRecord]) -> None:
        """
        Upsert document rows.

        Parameters
        ----------
        documents : Sequence[DocumentRecord]
            Document records to upsert.
        """

        if not documents:
            return

        sql = """
        INSERT INTO documents (
            doc_id,
            source,
            source_relpath,
            ticker,
            company,
            cik,
            accession,
            filing_type,
            filing_date,
            period_end_date,
            filing_quarter,
            metadata
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        ON CONFLICT (doc_id) DO UPDATE
        SET
            source = EXCLUDED.source,
            source_relpath = EXCLUDED.source_relpath,
            ticker = EXCLUDED.ticker,
            company = EXCLUDED.company,
            cik = EXCLUDED.cik,
            accession = EXCLUDED.accession,
            filing_type = EXCLUDED.filing_type,
            filing_date = EXCLUDED.filing_date,
            period_end_date = EXCLUDED.period_end_date,
            filing_quarter = EXCLUDED.filing_quarter,
            metadata = EXCLUDED.metadata,
            updated_at = NOW();
        """

        params = [
            (
                row.doc_id,
                row.source,
                row.source_relpath,
                row.ticker,
                row.company,
                row.cik,
                row.accession,
                row.filing_type,
                row.filing_date,
                row.period_end_date,
                row.filing_quarter,
                Jsonb(row.metadata),
            )
            for row in documents
        ]

        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.executemany(sql, params)

    def upsert_chunks(self, chunks: Sequence[ChunkRecord]) -> None:
        """
        Upsert chunk rows.

        Parameters
        ----------
        chunks : Sequence[ChunkRecord]
            Chunk records to upsert.
        """

        if not chunks:
            return

        embedding_dim = len(chunks[0].embedding)
        if embedding_dim <= 0:
            raise ValueError("Embedding dimension must be positive.")
        for row in chunks[1:]:
            if len(row.embedding) != embedding_dim:
                raise ValueError("Mixed embedding dimensions in chunk batch.")

        self.ensure_ann_index(embedding_dim)
        self.ensure_sparse_method_for_indexing()

        sql = """
        INSERT INTO chunks (
            chunk_id,
            doc_id,
            chunk_index,
            page_no,
            headings,
            source,
            text,
            retrieval_text,
            retrieval_context,
            metadata,
            embedding
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector
        )
        ON CONFLICT (chunk_id) DO UPDATE
        SET
            doc_id = EXCLUDED.doc_id,
            chunk_index = EXCLUDED.chunk_index,
            page_no = EXCLUDED.page_no,
            headings = EXCLUDED.headings,
            source = EXCLUDED.source,
            text = EXCLUDED.text,
            retrieval_text = EXCLUDED.retrieval_text,
            retrieval_context = EXCLUDED.retrieval_context,
            metadata = EXCLUDED.metadata,
            embedding = EXCLUDED.embedding,
            updated_at = NOW();
        """

        params = [
            (
                row.chunk_id,
                row.doc_id,
                row.chunk_index,
                row.page_no,
                row.headings,
                row.source,
                row.text,
                row.retrieval_text,
                row.retrieval_context,
                Jsonb(row.metadata),
                vector_literal(row.embedding),
            )
            for row in chunks
        ]

        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.executemany(sql, params)

    def existing_chunk_ids(self, chunk_ids: Iterable[str]) -> set[str]:
        """
        Return chunk IDs that already exist.

        Parameters
        ----------
        chunk_ids : Iterable[str]
            Candidate chunk IDs.

        Returns
        -------
        set[str]
            Existing IDs.
        """

        ids = [chunk_id for chunk_id in chunk_ids if chunk_id]
        if not ids:
            return set()

        with self.connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("SELECT chunk_id FROM chunks WHERE chunk_id = ANY(%s);", (ids,))
                rows = cur.fetchall()

        return {str(row["chunk_id"]) for row in rows}

    def hybrid_search(
        self,
        *,
        query_text: str,
        query_vector: Sequence[float],
        top_k_semantic: int,
        top_k_sparse: int,
        top_k_final: int,
        alpha: float,
        rrf_k: int,
        filters: RetrievalFilters | None,
    ) -> list[HybridSearchRow]:
        """
        Run hybrid dense + sparse retrieval with optional pre-filters.

        Parameters
        ----------
        query_text : str
            Input query text.
        query_vector : Sequence[float]
            Query embedding vector.
        top_k_semantic : int
            Dense candidate count.
        top_k_sparse : int
            Sparse candidate count.
        top_k_final : int
            Final fused result count.
        alpha : float
            Dense weight in weighted reciprocal rank fusion.
        rrf_k : int
            Reciprocal rank offset constant.
        filters : RetrievalFilters | None
            Optional ticker/date constraints.

        Returns
        -------
        list[HybridSearchRow]
            Typed rows for downstream conversion.

        TODO's
        ------
        - Add ef_search parameter to control HNSW search breadth (currently uses default).
        """

        self.ensure_sparse_method_for_retrieval()

        params: dict[str, Any] = {
            "query_text": query_text,
            "query_vector": vector_literal(query_vector),
            "top_k_semantic": max(1, int(top_k_semantic)),
            "top_k_sparse": max(1, int(top_k_sparse)),
            "top_k_final": max(1, int(top_k_final)),
            "alpha": float(alpha),
            "rrf_k": max(1, int(rrf_k)),
        }

        where_clauses: list[SQL] = []
        if filters is not None:
            tickers = list(filters.normalized_tickers())
            if tickers:
                where_clauses.append(SQL("d.ticker = ANY(%(tickers)s)"))
                params["tickers"] = tickers
            if filters.filing_date_from is not None:
                where_clauses.append(SQL("d.filing_date >= %(filing_date_from)s"))
                params["filing_date_from"] = filters.filing_date_from
            if filters.filing_date_to is not None:
                where_clauses.append(SQL("d.filing_date <= %(filing_date_to)s"))
                params["filing_date_to"] = filters.filing_date_to

        where_sql = SQL("")
        if where_clauses:
            where_sql = SQL("WHERE ") + SQL(" AND ").join(where_clauses)

        vector_dim = self.resolve_embedding_dim()
        embedding_expr: Composable = SQL("embedding")
        query_vector_expr: Composable = SQL("%(query_vector)s::vector")
        if vector_dim is not None:
            vector_type = SQL("vector({})").format(SqlLiteral(vector_dim))
            embedding_expr = SQL("embedding::{}").format(vector_type)
            query_vector_expr = SQL("%(query_vector)s::{}").format(vector_type)

        sparse_sql: Composable
        if self.sparse_search_method == "bm25":
            bm25_score_expr = SQL("retrieval_text <@> to_bm25query(%(query_text)s, {})").format(
                SqlLiteral("idx_chunks_retrieval_text_bm25")
            )
            sparse_sql = SQL(
                """
        sparse AS (
            SELECT
                chunk_id,
                ROW_NUMBER() OVER (ORDER BY {bm25_score_expr} ASC) AS rank_sparse
            FROM filtered
            WHERE {bm25_score_expr} < 0.0
            ORDER BY {bm25_score_expr} ASC
            LIMIT %(top_k_sparse)s
        ),
        """
            ).format(bm25_score_expr=bm25_score_expr)
        else:
            tsquery_expr = SQL("plainto_tsquery('english', %(query_text)s)")
            fts_score_expr = SQL("ts_rank_cd(search_tsv, {tsquery_expr})").format(tsquery_expr=tsquery_expr)
            sparse_sql = SQL(
                """
        sparse AS (
            SELECT
                chunk_id,
                ROW_NUMBER() OVER (ORDER BY {fts_score_expr} DESC) AS rank_sparse
            FROM filtered
            WHERE search_tsv @@ {tsquery_expr}
            ORDER BY {fts_score_expr} DESC
            LIMIT %(top_k_sparse)s
        ),
        """
            ).format(fts_score_expr=fts_score_expr, tsquery_expr=tsquery_expr)

        query_sql = SQL(
            """
        WITH filtered AS (
            SELECT
                c.chunk_id,
                c.embedding,
                c.search_tsv,
                c.retrieval_text
            FROM chunks c
            JOIN documents d ON d.doc_id = c.doc_id
            {where_sql}
        ),
        dense AS (
            SELECT
                chunk_id,
                ROW_NUMBER() OVER (ORDER BY {embedding_expr} <=> {query_vector_expr}) AS rank_dense
            FROM filtered
            ORDER BY {embedding_expr} <=> {query_vector_expr}
            LIMIT %(top_k_semantic)s
        ),
        {sparse_sql}
        candidates AS (
            SELECT chunk_id, rank_dense, NULL::INTEGER AS rank_sparse FROM dense
            UNION ALL
            SELECT chunk_id, NULL::INTEGER AS rank_dense, rank_sparse FROM sparse
        ),
        fused AS (
            SELECT
                chunk_id,
                MIN(rank_dense) AS rank_dense,
                MIN(rank_sparse) AS rank_sparse,
                COALESCE(%(alpha)s * (1.0 / (%(rrf_k)s + MIN(rank_dense))), 0.0) +
                COALESCE((1.0 - %(alpha)s) * (1.0 / (%(rrf_k)s + MIN(rank_sparse))), 0.0) AS score
            FROM candidates
            GROUP BY chunk_id
        )
        SELECT
            f.score,
            c.chunk_id,
            c.doc_id,
            c.page_no,
            c.headings,
            c.source,
            c.text,
            c.retrieval_text,
            c.retrieval_context,
            c.metadata
        FROM fused f
        JOIN chunks c ON c.chunk_id = f.chunk_id
        ORDER BY f.score DESC
        LIMIT %(top_k_final)s;
        """
        ).format(
            where_sql=where_sql,
            embedding_expr=embedding_expr,
            query_vector_expr=query_vector_expr,
            sparse_sql=sparse_sql,
        )

        with self.connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(query_sql, params)
                rows = cur.fetchall()

        out: list[HybridSearchRow] = []
        for row in rows:
            metadata_raw = row["metadata"]
            metadata = dict(metadata_raw) if isinstance(metadata_raw, dict) else {}
            headings_raw = row["headings"]
            headings = list(headings_raw) if isinstance(headings_raw, list) else []
            out.append(
                HybridSearchRow(
                    score=float(row["score"]),
                    chunk_id=str(row["chunk_id"]),
                    doc_id=str(row["doc_id"]),
                    page_no=int(row["page_no"]) if isinstance(row["page_no"], int) else None,
                    headings=[str(item) for item in headings],
                    source=str(row["source"]),
                    text=str(row["text"]),
                    retrieval_text=str(row["retrieval_text"]),
                    retrieval_context=(
                        str(row["retrieval_context"]) if isinstance(row["retrieval_context"], str) else None
                    ),
                    metadata=metadata,
                )
            )
        return out

    def clear_all(self) -> None:
        """
        Delete all corpus rows and sparse method compatibility state.
        """

        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("TRUNCATE TABLE chunks, documents RESTART IDENTITY CASCADE;")
                cur.execute("DELETE FROM retrieval_runtime_config WHERE id = 1;")
        self._sparse_method_verified_for_indexing = False
        self._sparse_method_verified_for_retrieval = False

    def list_ingested_companies(self) -> list[IngestedCompanyRow]:
        """
        Return distinct indexed ticker/company pairs from `documents`.
        """

        sql = """
        SELECT
            UPPER(TRIM(ticker)) AS ticker,
            NULLIF(TRIM(company), '') AS company
        FROM documents
        WHERE ticker IS NOT NULL
          AND TRIM(ticker) <> ''
        GROUP BY UPPER(TRIM(ticker)), NULLIF(TRIM(company), '')
        ORDER BY UPPER(TRIM(ticker)) ASC, NULLIF(TRIM(company), '') ASC;
        """

        with self.connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql)
                rows = cur.fetchall()

        out: list[IngestedCompanyRow] = []
        seen: set[str] = set()
        for row in rows:
            ticker_raw = row["ticker"]
            ticker = str(ticker_raw).strip().upper()
            if not ticker or ticker in seen:
                continue
            seen.add(ticker)
            company_raw = row["company"]
            company = None
            if isinstance(company_raw, str):
                company_text = company_raw.strip()
                if company_text:
                    company = company_text
            out.append(IngestedCompanyRow(ticker=ticker, company=company))
        return out

    def export_schema_snapshot(self) -> dict[str, Any]:
        """
        Return lightweight row counts for debugging/validation.
        """

        with self.connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("SELECT COUNT(*) AS n FROM documents;")
                documents_row = cur.fetchone()
                if documents_row is None:
                    raise RuntimeError("Failed to fetch documents row count.")
                n_documents = int(documents_row["n"])
                cur.execute("SELECT COUNT(*) AS n FROM chunks;")
                chunks_row = cur.fetchone()
                if chunks_row is None:
                    raise RuntimeError("Failed to fetch chunks row count.")
                n_chunks = int(chunks_row["n"])

        return {
            "documents": n_documents,
            "chunks": n_chunks,
            "dsn": self.redacted_dsn(),
            "schema": self.postgres_schema or "public",
        }

    def redacted_dsn(self) -> str:
        """
        Return a log-safe DSN.
        """

        if "@" not in self.dsn:
            return self.dsn
        prefix, suffix = self.dsn.split("@", 1)
        if ":" in prefix:
            user = prefix.split(":", 1)[0]
            return f"{user}:***@{suffix}"
        return "***@" + suffix


def dump_json(data: dict[str, Any]) -> str:
    """
    Serialize a dictionary using stable JSON formatting.
    """

    return json.dumps(data, ensure_ascii=False, sort_keys=True)
