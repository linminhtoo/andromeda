"""
Inspect indexed chunks stored in PostgreSQL.

Examples
--------
  python -m scripts.inspect_collection --limit 5
  python -m scripts.inspect_collection --chunk-id "<chunk_id>"
  python -m scripts.inspect_collection --ticker NVDA --filing-date-from 2024-01-01
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import date
from typing import Any

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row
from psycopg.sql import SQL

from andromeda.retrieval.db import normalize_iso_date


def maybe_truncate(text: str, *, max_chars: int | None) -> str:
    if max_chars is None or len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


def postgres_dsn(arg_dsn: str | None) -> str:
    dsn = (arg_dsn or os.getenv("POSTGRES_DSN") or os.getenv("DATABASE_URL") or "").strip()
    if not dsn:
        raise SystemExit("Missing PostgreSQL DSN: set --postgres-dsn or POSTGRES_DSN/DATABASE_URL.")
    return dsn


def parse_date(name: str, value: str | None) -> date | None:
    parsed = normalize_iso_date(value)
    if value and not parsed:
        raise SystemExit(f"Invalid {name}: {value}. Expected YYYY-MM-DD.")
    return parsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect indexed chunks in PostgreSQL.")
    parser.add_argument("--postgres-dsn", default=None, help="Overrides POSTGRES_DSN/DATABASE_URL.")
    parser.add_argument("--chunk-id", default=None, help="Exact chunk_id match.")
    parser.add_argument("--ticker", default=None, help="Restrict to a ticker symbol.")
    parser.add_argument("--filing-date-from", default=None, help="Inclusive filing date lower bound (YYYY-MM-DD).")
    parser.add_argument("--filing-date-to", default=None, help="Inclusive filing date upper bound (YYYY-MM-DD).")
    parser.add_argument("--limit", type=int, default=10, help="Maximum rows to print (ignored when --chunk-id is set).")
    parser.add_argument("--max-chars", type=int, default=400, help="Max chars for large text fields; 0 disables.")
    parser.add_argument("--json", action="store_true", help="Print JSONL records.")
    return parser.parse_args()


def select_rows(
    *,
    dsn: str,
    chunk_id: str | None,
    ticker: str | None,
    filing_date_from: date | None,
    filing_date_to: date | None,
    limit: int,
) -> list[dict[str, Any]]:
    where: list[SQL] = []
    params: dict[str, Any] = {}

    if chunk_id:
        where.append(SQL("c.chunk_id = %(chunk_id)s"))
        params["chunk_id"] = chunk_id
    if ticker:
        where.append(SQL("d.ticker = %(ticker)s"))
        params["ticker"] = ticker.strip().upper()
    if filing_date_from is not None:
        where.append(SQL("d.filing_date >= %(filing_date_from)s"))
        params["filing_date_from"] = filing_date_from
    if filing_date_to is not None:
        where.append(SQL("d.filing_date <= %(filing_date_to)s"))
        params["filing_date_to"] = filing_date_to

    if chunk_id:
        row_limit = 1
    else:
        row_limit = max(1, int(limit))
    params["limit"] = row_limit

    where_sql = SQL("")
    if where:
        where_sql = SQL("WHERE ") + SQL(" AND ").join(where)

    raw_sql = SQL(
        """
        SELECT
            c.chunk_id,
            c.doc_id,
            c.page_no,
            c.headings,
            c.source,
            c.text,
            c.retrieval_text,
            c.retrieval_context,
            c.metadata,
            d.ticker,
            d.company,
            d.filing_type,
            d.filing_date
        FROM chunks c
        JOIN documents d ON d.doc_id = c.doc_id
        {where_sql}
        ORDER BY d.filing_date DESC NULLS LAST, c.doc_id, c.chunk_index
        LIMIT %(limit)s;
    """
    ).format(where_sql=where_sql)

    with psycopg.connect(dsn) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(raw_sql, params)
            rows = cur.fetchall()
    return [dict(row) for row in rows]


def render_row(row: dict[str, Any], *, max_chars: int | None) -> dict[str, Any]:
    metadata = row["metadata"]
    if not isinstance(metadata, dict):
        metadata = {}

    return {
        "chunk_id": row["chunk_id"],
        "doc_id": row["doc_id"],
        "ticker": row["ticker"],
        "company": row["company"],
        "filing_type": row["filing_type"],
        "filing_date": row["filing_date"].isoformat() if row["filing_date"] else None,
        "page_no": row["page_no"],
        "headings": row["headings"],
        "source": row["source"],
        "retrieval_text": maybe_truncate(str(row["retrieval_text"] or ""), max_chars=max_chars),
        "retrieval_context": maybe_truncate(str(row["retrieval_context"] or ""), max_chars=max_chars),
        "text": maybe_truncate(str(row["text"] or ""), max_chars=max_chars),
        "metadata_keys": sorted(metadata.keys()),
    }


def print_row(row: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(row, ensure_ascii=False))
        return
    print(f"chunk_id: {row['chunk_id']}")
    print(f"doc_id: {row['doc_id']} | ticker: {row['ticker']} | filing_date: {row['filing_date']}")
    print(f"retrieval_context: {row['retrieval_context']}")
    print(f"retrieval_text: {row['retrieval_text']}")
    print("---")


def main() -> None:
    load_dotenv()
    args = parse_args()
    dsn = postgres_dsn(args.postgres_dsn)

    rows = select_rows(
        dsn=dsn,
        chunk_id=(args.chunk_id.strip() if isinstance(args.chunk_id, str) and args.chunk_id.strip() else None),
        ticker=(args.ticker.strip() if isinstance(args.ticker, str) and args.ticker.strip() else None),
        filing_date_from=parse_date("filing-date-from", args.filing_date_from),
        filing_date_to=parse_date("filing-date-to", args.filing_date_to),
        limit=args.limit,
    )

    max_chars = None if int(args.max_chars or 0) <= 0 else int(args.max_chars)
    for row in rows:
        rendered = render_row(row, max_chars=max_chars)
        print_row(rendered, as_json=bool(args.json))


if __name__ == "__main__":
    main()
