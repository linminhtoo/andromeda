"""
Build a PostgreSQL hybrid index from exported chunks.

Expected input is a chunk export directory containing:
  - doc_index.jsonl
  - chunks/ (per-document JSONL files)

This script embeds chunk text and upserts corpus rows into PostgreSQL.
Retrieval is later done with pgvector (dense) + PostgreSQL FTS (sparse).
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from dotenv import load_dotenv
from loguru import logger
from tqdm import tqdm

from finrag.context_support import apply_context_strategy, context_builder_from_metadata
from finrag.dataclasses import DocChunk
from finrag.llm_clients import get_llm_client
from finrag.retriever import PostgresHybridRetriever

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


@dataclass
class Args:
    ingest_output_dir: str
    postgres_dsn: str | None
    postgres_schema: str | None
    llm_provider: str | None
    contextual_llm_provider: str | None
    dense_model: str
    contextual_model: str | None
    dense_base_url: str | None
    contextual_base_url: str | None
    max_docs: int | None
    batch_size: int
    context: str
    context_window: int
    context_metadata_key: str
    context_max_concurrency: int
    ann_hnsw_m: int | None
    ann_hnsw_ef_construction: int | None
    reset_corpus: bool
    recreate_ann_index: bool
    allow_default_schema_mutations: bool
    skip_existing_chunks: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DocIndexEntry:
    """
    Typed `doc_index.jsonl` row used by indexing.
    """

    chunks_path: str

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> DocIndexEntry:
        if "chunks_path" not in value:
            raise ValueError("doc_index row is missing required key: chunks_path")
        chunks_path_raw = value["chunks_path"]
        if not isinstance(chunks_path_raw, str) or not chunks_path_raw.strip():
            raise ValueError(f"Invalid chunks_path in doc_index row: {chunks_path_raw!r}")
        return cls(chunks_path=chunks_path_raw.strip())


@dataclass(frozen=True)
class ChunkJsonRow:
    """
    Typed chunk JSONL row used to build `DocChunk`.
    """

    id: str
    doc_id: str
    text: str
    page_no: int | None
    headings: list[str]
    source: str
    metadata: dict[str, Any] | None

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> ChunkJsonRow:
        if "id" not in value:
            raise ValueError("chunk row is missing required key: id")
        if "doc_id" not in value:
            raise ValueError("chunk row is missing required key: doc_id")
        if "text" not in value:
            raise ValueError("chunk row is missing required key: text")

        row_id = value["id"]
        doc_id = value["doc_id"]
        text = value["text"]
        if not isinstance(row_id, str):
            raise ValueError(f"chunk id must be a string, got {type(row_id).__name__}")
        if not isinstance(doc_id, str):
            raise ValueError(f"chunk doc_id must be a string, got {type(doc_id).__name__}")
        if not isinstance(text, str):
            raise ValueError(f"chunk text must be a string, got {type(text).__name__}")

        page_no_raw = value["page_no"] if "page_no" in value else None
        page_no = page_no_raw if isinstance(page_no_raw, int) else None

        headings_raw = value["headings"] if "headings" in value else None
        headings: list[str] = []
        if isinstance(headings_raw, list):
            headings = [str(item) for item in headings_raw]

        source_raw = value["source"] if "source" in value else ""
        source = source_raw if isinstance(source_raw, str) else str(source_raw)

        metadata_raw = value["metadata"] if "metadata" in value else None
        metadata = dict(metadata_raw) if isinstance(metadata_raw, dict) else None

        return cls(
            id=row_id, doc_id=doc_id, text=text, page_no=page_no, headings=headings, source=source, metadata=metadata
        )


def parse_args() -> Args:
    def positive_int(value: str) -> int:
        parsed = int(value)
        if parsed <= 0:
            raise argparse.ArgumentTypeError("must be > 0")
        return parsed

    parser = argparse.ArgumentParser(description="Build PostgreSQL retrieval index from chunk exports.")
    parser.add_argument(
        "--ingest-output-dir",
        required=True,
        help="Directory produced by scripts/chunk.py (must contain doc_index.jsonl and chunks/).",
    )
    parser.add_argument(
        "--postgres-dsn", default=None, help="PostgreSQL DSN (defaults to POSTGRES_DSN or DATABASE_URL env vars)."
    )
    parser.add_argument(
        "--postgres-schema",
        default=(os.getenv("POSTGRES_SCHEMA") or None),
        help="Optional PostgreSQL schema name for experiment isolation (defaults to POSTGRES_SCHEMA env var).",
    )
    parser.add_argument("--llm-provider", default=None, help="Embedding provider (defaults to env LLM_PROVIDER).")
    parser.add_argument(
        "--contextual-llm-provider",
        default=None,
        help="Provider for contextualization calls (defaults to --llm-provider).",
    )
    parser.add_argument("--dense-model", default="text-embedding-3-large", help="Embedding model name.")
    parser.add_argument(
        "--contextual-model", default=None, help="Chat model for context generation (defaults to provider default)."
    )
    parser.add_argument(
        "--dense-base-url", default=None, help="OpenAI-compatible embedding base URL override (when provider=openai)."
    )
    parser.add_argument(
        "--contextual-base-url",
        default=None,
        help="OpenAI-compatible chat base URL override for contextualization (provider=openai).",
    )
    parser.add_argument("--max-docs", type=int, default=None, help="Optional cap on documents to index.")
    parser.add_argument("--batch-size", type=int, default=128, help="Batch size for embedding/upsert.")
    parser.add_argument(
        "--context",
        default="none",
        choices=["none", "document", "neighbors", "metadata"],
        help="Context strategy for embedding text (default: none).",
    )
    parser.add_argument("--context-window", type=int, default=2, help="Neighbor window size when --context=neighbors.")
    parser.add_argument(
        "--context-max-concurrency", type=int, default=32, help="Max concurrent context-generation calls."
    )
    parser.add_argument(
        "--context-metadata-key", default="retrieval_context", help="Metadata key used to store contextual text."
    )
    parser.add_argument(
        "--ann-hnsw-m",
        type=positive_int,
        default=None,
        help="Optional HNSW index parameter m (higher can improve recall at higher memory/build cost).",
    )
    parser.add_argument(
        "--ann-hnsw-ef-construction",
        type=positive_int,
        default=None,
        help="Optional HNSW index parameter ef_construction (higher can improve recall at higher build cost).",
    )
    parser.add_argument(
        "--reset-corpus",
        "--truncate",
        dest="reset_corpus",
        action="store_true",
        help="Delete all existing corpus rows before indexing (--truncate is kept as a legacy alias).",
    )
    parser.add_argument(
        "--recreate-ann-index",
        action="store_true",
        help="Drop and recreate ANN indexes so new HNSW settings take effect.",
    )
    parser.add_argument(
        "--allow-default-schema-mutations",
        action="store_true",
        help="Allow destructive flags against the default schema (dangerous; use only intentionally).",
    )
    parser.add_argument(
        "--skip-existing-chunks", action="store_true", help="Skip chunk IDs that already exist in PostgreSQL."
    )

    ns = parser.parse_args()
    return Args(
        ingest_output_dir=ns.ingest_output_dir,
        postgres_dsn=ns.postgres_dsn,
        postgres_schema=(str(ns.postgres_schema).strip() if ns.postgres_schema is not None else None) or None,
        llm_provider=ns.llm_provider,
        contextual_llm_provider=ns.contextual_llm_provider,
        dense_model=ns.dense_model,
        contextual_model=ns.contextual_model,
        dense_base_url=ns.dense_base_url,
        contextual_base_url=ns.contextual_base_url,
        max_docs=ns.max_docs,
        batch_size=ns.batch_size,
        context=ns.context,
        context_window=ns.context_window,
        context_metadata_key=ns.context_metadata_key,
        context_max_concurrency=ns.context_max_concurrency,
        ann_hnsw_m=ns.ann_hnsw_m,
        ann_hnsw_ef_construction=ns.ann_hnsw_ef_construction,
        reset_corpus=bool(ns.reset_corpus),
        recreate_ann_index=bool(ns.recreate_ann_index),
        allow_default_schema_mutations=bool(ns.allow_default_schema_mutations),
        skip_existing_chunks=bool(ns.skip_existing_chunks),
    )


def json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, set):
        return list(value)
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()  # type: ignore[no-any-return]
        except Exception:  # noqa: BLE001
            pass
    return str(value)


def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            yield json.loads(line)


def resolve_chunks_path(doc: DocIndexEntry, ingest_root: Path) -> Path:
    chunks_path = Path(doc.chunks_path).expanduser()
    if not chunks_path.is_absolute():
        chunks_path = (ingest_root / chunks_path).resolve()
    return chunks_path


def chunk_from_dict(data: ChunkJsonRow) -> DocChunk:
    return DocChunk(
        id=data.id,
        doc_id=data.doc_id,
        text=data.text,
        page_no=data.page_no,
        headings=list(data.headings),
        source=data.source,
        metadata=data.metadata,
    )


def batched(items: list[DocChunk], batch_size: int) -> Iterable[list[DocChunk]]:
    size = max(1, int(batch_size))
    for idx in range(0, len(items), size):
        yield items[idx : idx + size]


def setup_logging(project_root: Path) -> Path:
    logs_dir = project_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    log_path = logs_dir / f"build_index_{timestamp}.log"

    logger.remove()
    logger.add(sys.stderr, level="INFO")
    logger.add(str(log_path), level="DEBUG")
    return log_path


def postgres_dsn_from_env(args_dsn: str | None) -> str:
    dsn = (args_dsn or os.getenv("POSTGRES_DSN") or os.getenv("DATABASE_URL") or "").strip()
    if not dsn:
        raise SystemExit("Missing PostgreSQL DSN: set --postgres-dsn or POSTGRES_DSN/DATABASE_URL.")
    return dsn


def main() -> int:
    args = parse_args()

    ingest_out = Path(args.ingest_output_dir).expanduser().resolve()
    doc_index_path = ingest_out / "doc_index.jsonl"
    if not doc_index_path.exists():
        raise SystemExit(f"Missing required file: {doc_index_path}")

    project_root = Path(__file__).resolve().parents[1]
    log_path = setup_logging(project_root)
    logger.info(f"Logging to: {log_path}")

    dsn = postgres_dsn_from_env(args.postgres_dsn)

    if (
        (args.reset_corpus or args.recreate_ann_index)
        and not args.postgres_schema
        and not args.allow_default_schema_mutations
    ):
        raise SystemExit(
            "Refusing destructive operation on default schema. Set --postgres-schema for an isolated experiment "
            "or pass --allow-default-schema-mutations to override."
        )

    dense_provider = (args.llm_provider or os.getenv("LLM_PROVIDER") or "openai").strip().lower()
    dense_kwargs: dict[str, Any] = {"embed_model": args.dense_model}
    if args.dense_base_url and dense_provider == "openai":
        dense_kwargs["base_url"] = args.dense_base_url
    llm_for_dense = get_llm_client(provider=args.llm_provider, **dense_kwargs)

    llm_for_context = None
    if args.context in {"document", "neighbors"}:
        context_provider = (
            (args.contextual_llm_provider or args.llm_provider or os.getenv("LLM_PROVIDER") or "openai").strip().lower()
        )

        context_kwargs: dict[str, Any] = {"embed_model": args.dense_model}
        if args.contextual_model:
            context_kwargs["chat_model"] = args.contextual_model
        if args.contextual_base_url and context_provider == "openai":
            context_kwargs["base_url"] = args.contextual_base_url
        llm_for_context = get_llm_client(provider=(args.contextual_llm_provider or args.llm_provider), **context_kwargs)

    retriever = PostgresHybridRetriever(
        llm_client=llm_for_dense,
        dsn=dsn,
        context_builder=context_builder_from_metadata(key=args.context_metadata_key),
        retrieval_context_key=args.context_metadata_key,
        postgres_schema=args.postgres_schema,
        ann_hnsw_m=args.ann_hnsw_m,
        ann_hnsw_ef_construction=args.ann_hnsw_ef_construction,
    )

    if args.reset_corpus:
        logger.warning("Truncating existing PostgreSQL corpus rows")
        retriever.db.clear_all()

    if args.recreate_ann_index:
        logger.warning("Dropping ANN indexes for recreation")
        retriever.db.drop_ann_indexes()
        if not args.reset_corpus:
            retriever.db.ensure_ann_index()

    docs = [DocIndexEntry.from_mapping(item) for item in iter_jsonl(doc_index_path)]
    if args.max_docs is not None:
        docs = docs[: max(0, int(args.max_docs))]
    logger.info(f"Documents to index: {len(docs)}")

    started_at = time.time()
    total_docs = 0
    total_chunks = 0
    skipped_docs = 0
    skipped_chunks = 0
    had_error = False

    def handle_signal(signum, _frame):
        raise KeyboardInterrupt(f"Received signal {signum}")

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        for doc in tqdm(docs, desc="indexing docs"):
            chunks_path = resolve_chunks_path(doc, ingest_out)
            if not chunks_path.exists():
                logger.warning(f"Missing chunk file, skipping: {chunks_path}")
                continue

            doc_chunks = [chunk_from_dict(ChunkJsonRow.from_mapping(item)) for item in iter_jsonl(chunks_path)]
            if not doc_chunks:
                continue

            if args.context in {"document", "neighbors", "metadata"}:
                apply_context_strategy(
                    doc_chunks,
                    strategy=args.context,
                    neighbor_window=args.context_window,
                    metadata_key=args.context_metadata_key,
                    max_concurrency=args.context_max_concurrency,
                    llm_for_context=llm_for_context,
                )

            chunks_to_index = doc_chunks
            if args.skip_existing_chunks:
                existing = retriever.existing_chunk_ids(chunk.id for chunk in doc_chunks)
                if existing:
                    chunks_to_index = [chunk for chunk in doc_chunks if chunk.id not in existing]
                    skipped_chunks += len(existing)
                if not chunks_to_index:
                    skipped_docs += 1
                    continue

            logger.debug(f"Indexing doc_id={doc_chunks[0].doc_id} chunks={len(chunks_to_index)}")
            for batch in batched(chunks_to_index, batch_size=args.batch_size):
                retriever.index(batch)

            total_docs += 1
            total_chunks += len(chunks_to_index)
    except BaseException as exc:  # noqa: BLE001
        had_error = True
        logger.exception(f"Indexing interrupted: {exc}")

    snapshot = retriever.db.export_schema_snapshot()
    run_info = {
        "args": args.to_dict(),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(started_at)),
        "elapsed_s": round(time.time() - started_at, 3),
        "ingest_output_dir": str(ingest_out),
        "indexed_docs": total_docs,
        "indexed_chunks": total_chunks,
        "skipped_docs": skipped_docs,
        "skipped_chunks": skipped_chunks,
        "had_error": had_error,
        "database": snapshot,
    }

    run_info_path = ingest_out / "build_index_run_info.json"
    run_info_path.write_text(json.dumps(run_info, ensure_ascii=False, indent=2, default=json_default), encoding="utf-8")

    if had_error:
        logger.warning(f"Indexing stopped early. indexed_docs={total_docs} indexed_chunks={total_chunks}")
    else:
        logger.success(f"Done. indexed_docs={total_docs} indexed_chunks={total_chunks}")
    logger.success(f"Elapsed time: {round(time.time() - started_at, 2)}s. Wrote: {run_info_path}")
    return 1 if had_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
