from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

from andromeda.dataclasses import DocChunk
from andromeda.processing.metadata_models import chunk_metadata_from_value

_FILENAME_RE = re.compile(
    r"^(?P<ticker>[A-Za-z0-9.]+)_(?P<accession>\d{18})_(?P<form>[^_]+)_(?P<date>\d{4}-\d{2}-\d{2})$"
)


@dataclass(frozen=True)
class ChunkExportDoc:
    doc_id: str
    source: str
    chunks_path: str
    relpath: str | None = None
    ticker: str | None = None
    filing_type: str | None = None
    filing_date: str | None = None
    year: int | None = None
    company: str | None = None


@dataclass(frozen=True)
class ParsedDocFromSource:
    ticker: str
    filing_type: str
    filing_date: str
    year: int | None


@dataclass(frozen=True)
class DocIndexRow:
    doc_id: str
    source: str
    relpath: str | None
    chunks_path: str

    @classmethod
    def from_json_obj(cls, value: object) -> DocIndexRow | None:
        if not isinstance(value, dict):
            return None

        doc_id_raw = value["doc_id"] if "doc_id" in value else ""
        chunks_path_raw = value["chunks_path"] if "chunks_path" in value else ""
        source_raw = value["source"] if "source" in value else ""
        relpath_raw = value["relpath"] if "relpath" in value else ""

        doc_id = doc_id_raw if isinstance(doc_id_raw, str) else str(doc_id_raw)
        chunks_path = chunks_path_raw if isinstance(chunks_path_raw, str) else str(chunks_path_raw)
        source = source_raw if isinstance(source_raw, str) else str(source_raw)
        relpath = relpath_raw if isinstance(relpath_raw, str) else str(relpath_raw)
        relpath = relpath or None

        if not doc_id or not chunks_path:
            return None
        return cls(doc_id=doc_id, source=source, relpath=relpath, chunks_path=chunks_path)


@dataclass(frozen=True)
class ChunkExportRow:
    id: str
    doc_id: str
    text: str
    page_no: int | None
    headings: list[str]
    source: str
    metadata: dict[str, Any] | None

    @classmethod
    def from_json_obj(cls, value: object) -> ChunkExportRow | None:
        if not isinstance(value, dict):
            return None
        if "id" not in value or "doc_id" not in value:
            return None

        row_id = value["id"]
        row_doc_id = value["doc_id"]
        row_text = value["text"] if "text" in value else ""
        row_source = value["source"] if "source" in value else ""
        row_page_no = value["page_no"] if "page_no" in value else None
        row_headings = value["headings"] if "headings" in value else None
        row_metadata = value["metadata"] if "metadata" in value else None

        if not isinstance(row_id, str) or not isinstance(row_doc_id, str):
            return None

        headings: list[str] = []
        if isinstance(row_headings, list):
            headings = [str(item) for item in row_headings]

        return cls(
            id=row_id,
            doc_id=row_doc_id,
            text=row_text if isinstance(row_text, str) else str(row_text),
            page_no=row_page_no if isinstance(row_page_no, int) else None,
            headings=headings,
            source=row_source if isinstance(row_source, str) else str(row_source),
            metadata=dict(row_metadata) if isinstance(row_metadata, dict) else None,
        )


def _parse_doc_from_source(source: str | None, relpath: str | None) -> ParsedDocFromSource | None:
    path_s = (relpath or source or "").strip()
    if not path_s:
        return None
    stem = Path(path_s).stem
    m = _FILENAME_RE.match(stem)
    if not m:
        return None
    ticker = m.group("ticker").upper()
    filing_type = m.group("form").upper()
    filing_date = m.group("date")
    try:
        year = int(filing_date.split("-", 1)[0])
    except Exception:
        year = None
    return ParsedDocFromSource(ticker=ticker, filing_type=filing_type, filing_date=filing_date, year=year)


def _resolve_chunks_path(ingest_output_dir: Path, chunks_path: str) -> Path:
    p = Path(chunks_path).expanduser()
    if not p.is_absolute():
        p = (ingest_output_dir / p).resolve()
    return p


def _peek_company_from_chunks(chunks_path: Path, *, max_lines: int = 30) -> str | None:
    try:
        with chunks_path.open("r", encoding="utf-8") as f:
            for i, line in enumerate(f, start=1):
                if i > max_lines:
                    break
                line = line.strip()
                if not line:
                    continue
                row = ChunkExportRow.from_json_obj(json.loads(line))
                if row is None:
                    continue
                parsed = chunk_metadata_from_value(row.metadata)
                if parsed.doc and parsed.doc.company and parsed.doc.company.strip():
                    return parsed.doc.company.strip()
    except Exception:
        return None
    return None


def iter_chunk_export_docs(
    ingest_output_dir: str | Path,
    *,
    tickers: Iterable[str] | None = None,
    forms: Iterable[str] | None = None,
    max_docs: int | None = None,
) -> Iterator[ChunkExportDoc]:
    """
    Iterate the chunk export "doc index" (produced by `scripts/chunk.py`).

    `ingest_output_dir` is expected to contain:
      - doc_index.jsonl
      - chunks/ (per-document chunk JSONL files)
    """
    root = Path(ingest_output_dir).expanduser().resolve()
    doc_index_path = root / "doc_index.jsonl"
    if not doc_index_path.exists():
        raise FileNotFoundError(f"Missing doc index: {doc_index_path}")

    ticker_set = {t.upper() for t in tickers} if tickers else None
    form_set = {f.upper() for f in forms} if forms else None

    n = 0
    with doc_index_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = DocIndexRow.from_json_obj(json.loads(line))
            if row is None:
                continue

            parsed = _parse_doc_from_source(row.source, row.relpath)
            ticker = parsed.ticker if parsed is not None else None
            filing_type = parsed.filing_type if parsed is not None else None

            if ticker_set and isinstance(ticker, str) and ticker not in ticker_set:
                continue
            if form_set and isinstance(filing_type, str) and filing_type not in form_set:
                continue

            chunks_path = _resolve_chunks_path(root, row.chunks_path)
            company = _peek_company_from_chunks(chunks_path)

            yield ChunkExportDoc(
                doc_id=row.doc_id,
                source=row.source,
                relpath=row.relpath,
                chunks_path=str(chunks_path),
                ticker=ticker if isinstance(ticker, str) else None,
                filing_type=filing_type if isinstance(filing_type, str) else None,
                filing_date=parsed.filing_date if parsed is not None else None,
                year=parsed.year if parsed is not None else None,
                company=company,
            )

            n += 1
            if max_docs is not None and n >= max_docs:
                break


def iter_doc_chunks(chunks_path: str | Path, *, max_chunks: int | None = None) -> Iterator[DocChunk]:
    """
    Stream chunks from a per-document chunks JSONL file.
    """
    p = Path(chunks_path).expanduser()
    n = 0
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = ChunkExportRow.from_json_obj(json.loads(line))
            if row is None:
                continue
            yield DocChunk(
                id=row.id,
                doc_id=row.doc_id,
                text=row.text,
                page_no=row.page_no,
                headings=list(row.headings),
                source=row.source,
                metadata=row.metadata,
            )
            n += 1
            if max_chunks is not None and n >= max_chunks:
                break


def iter_all_chunks(
    ingest_output_dir: str | Path,
    *,
    tickers: Iterable[str] | None = None,
    forms: Iterable[str] | None = None,
    max_docs: int | None = None,
    max_chunks_per_doc: int | None = None,
) -> Iterator[DocChunk]:
    """
    Stream chunks across many documents from a chunk export directory.
    """
    for doc in iter_chunk_export_docs(ingest_output_dir, tickers=tickers, forms=forms, max_docs=max_docs):
        yield from iter_doc_chunks(doc.chunks_path, max_chunks=max_chunks_per_doc)
