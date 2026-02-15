import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException

from finrag.source_access import read_text_file


@dataclass(frozen=True)
class DocIndexSourceRow:
    doc_id: str
    relpath: str
    source: str
    markdown_path: str
    chunks_path: str
    num_chunks: int | None
    form_type: str
    filing_date: str

    @classmethod
    def from_json_obj(cls, value: object) -> "DocIndexSourceRow | None":
        if not isinstance(value, dict):
            return None
        doc_id_value = value["doc_id"] if "doc_id" in value else ""
        relpath_value = value["relpath"] if "relpath" in value else ""
        source_value = value["source"] if "source" in value else ""
        markdown_path_value = value["markdown_path"] if "markdown_path" in value else ""
        chunks_path_value = value["chunks_path"] if "chunks_path" in value else ""
        num_chunks_value = value["num_chunks"] if "num_chunks" in value else None
        form_type_value = value["form_type"] if "form_type" in value else ""
        filing_date_value = value["filing_date"] if "filing_date" in value else ""
        doc_id = doc_id_value if isinstance(doc_id_value, str) else str(doc_id_value)
        relpath = relpath_value if isinstance(relpath_value, str) else str(relpath_value)
        source = source_value if isinstance(source_value, str) else str(source_value)
        markdown_path = markdown_path_value if isinstance(markdown_path_value, str) else str(markdown_path_value)
        chunks_path = chunks_path_value if isinstance(chunks_path_value, str) else str(chunks_path_value)
        num_chunks = None
        if isinstance(num_chunks_value, int):
            num_chunks = num_chunks_value
        elif isinstance(num_chunks_value, float):
            num_chunks = int(num_chunks_value)
        form_type = form_type_value if isinstance(form_type_value, str) else str(form_type_value)
        filing_date = filing_date_value if isinstance(filing_date_value, str) else str(filing_date_value)
        return cls(
            doc_id=doc_id,
            relpath=relpath,
            source=source,
            markdown_path=markdown_path,
            chunks_path=chunks_path,
            num_chunks=num_chunks,
            form_type=form_type,
            filing_date=filing_date,
        )


@dataclass
class IngestedCompaniesCache:
    path: str | None = None
    mtime_ns: int | None = None
    use_yahoo: bool | None = None
    items: list[dict[str, object]] | None = None


class IngestedCompaniesService:
    """
    Resolve and cache ingested ticker/company list from doc_index.jsonl.
    """

    def __init__(self, *, project_root: Path):
        self.project_root = project_root
        self.cache = IngestedCompaniesCache()
        self.yahoo_company_resolver: object | None = None

    def list_companies(self) -> dict[str, object]:
        """
        Return payload used by `/ingested_companies` endpoint.
        """

        path = self.doc_index_path()
        if path is None:
            return {"items": [], "count": 0, "path": None, "warning": "FINRAG_DOC_INDEX_PATH not set"}

        mtime_ns = path.stat().st_mtime_ns
        use_yahoo = self.env_bool("FINRAG_INGESTED_COMPANIES_USE_YAHOO", default=True)
        if (
            self.cache.path == str(path)
            and self.cache.mtime_ns == mtime_ns
            and self.cache.use_yahoo == use_yahoo
            and isinstance(self.cache.items, list)
        ):
            return {"items": self.cache.items, "count": len(self.cache.items), "path": str(path)}

        items = self.read_ingested_companies(doc_index_path=path)
        self.cache.path = str(path)
        self.cache.mtime_ns = mtime_ns
        self.cache.use_yahoo = use_yahoo
        self.cache.items = items
        return {"items": items, "count": len(items), "path": str(path)}

    def doc_index_path(self) -> Path | None:
        raw = (os.getenv("FINRAG_DOC_INDEX_PATH") or "").strip()
        if not raw:
            return None
        path = Path(os.path.expanduser(raw))
        if not path.is_absolute():
            path = (self.project_root / path).resolve()
        else:
            path = path.resolve()
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail=f"doc_index.jsonl not found: {path}")
        return path

    def read_ingested_companies(self, *, doc_index_path: Path) -> list[dict[str, object]]:
        documents_by_ticker: dict[str, list[dict[str, object]]] = {}
        first_source_by_ticker: dict[str, Path] = {}
        with doc_index_path.open("r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                row = DocIndexSourceRow.from_json_obj(obj)
                if row is None:
                    continue
                ticker = self.ticker_from_relpath(row.relpath or row.source)
                if not ticker:
                    continue
                if ticker not in documents_by_ticker:
                    documents_by_ticker[ticker] = []
                documents_by_ticker[ticker].append(self.document_payload_from_row(row=row))
                source_path = row.markdown_path.strip() or row.source.strip()
                if source_path and ticker not in first_source_by_ticker:
                    first_source_by_ticker[ticker] = Path(source_path)

        items: list[dict[str, object]] = []
        for ticker in sorted(documents_by_ticker.keys()):
            docs = documents_by_ticker[ticker]
            docs.sort(key=self.document_sort_key, reverse=True)
            total_chunks = 0
            latest_filing_date = ""
            for doc in docs:
                num_chunks_value = doc["num_chunks"] if "num_chunks" in doc else None
                if isinstance(num_chunks_value, int) and num_chunks_value >= 0:
                    total_chunks += num_chunks_value
                filing_date_value = doc["filing_date"] if "filing_date" in doc else ""
                filing_date = filing_date_value if isinstance(filing_date_value, str) else ""
                if filing_date and (not latest_filing_date or filing_date > latest_filing_date):
                    latest_filing_date = filing_date

            source_path = first_source_by_ticker[ticker] if ticker in first_source_by_ticker else None
            company = self.resolve_company_name(ticker=ticker, md_path=source_path) if source_path else ticker
            items.append(
                {
                    "ticker": ticker,
                    "company": company,
                    "document_count": len(docs),
                    "total_chunks": total_chunks,
                    "latest_filing_date": latest_filing_date or None,
                    "documents": docs,
                }
            )

        return items

    @staticmethod
    def document_sort_key(document: dict[str, object]) -> tuple[str, str]:
        filing_date_value = document["filing_date"] if "filing_date" in document else ""
        filing_date = filing_date_value if isinstance(filing_date_value, str) else ""
        relpath_value = document["relpath"] if "relpath" in document else ""
        relpath = relpath_value if isinstance(relpath_value, str) else str(relpath_value)
        return filing_date, relpath

    @staticmethod
    def details_from_relpath(relpath: str) -> tuple[str, str]:
        if not relpath:
            return "", ""
        base = Path(relpath).name
        match = re.search(r"_([A-Za-z0-9-]+)_(\d{4}-\d{2}-\d{2})(?:\.[^.]*)?$", base)
        if not match:
            return "", ""
        return match.group(1).upper(), match.group(2)

    def document_payload_from_row(self, *, row: DocIndexSourceRow) -> dict[str, object]:
        inferred_form_type, inferred_filing_date = self.details_from_relpath(row.relpath)
        form_type = row.form_type.strip() or inferred_form_type
        filing_date = row.filing_date.strip() or inferred_filing_date
        return {
            "doc_id": row.doc_id.strip() or None,
            "relpath": row.relpath,
            "source": row.source,
            "chunks_path": row.chunks_path,
            "num_chunks": row.num_chunks,
            "form_type": form_type or None,
            "filing_date": filing_date or None,
        }

    @staticmethod
    def ticker_from_relpath(relpath: str) -> str:
        base = Path(relpath or "").name
        if "_" in base:
            return base.split("_", 1)[0].strip().upper()
        stem = Path(base).stem
        return stem.strip().upper()

    @staticmethod
    def strip_md_emphasis(value: str) -> str:
        cleaned = value.replace("**", "").replace("__", "").replace("*", "").replace("_", "")
        return " ".join(cleaned.split())

    @staticmethod
    def clean_company_heading(value: str) -> str:
        cleaned = " ".join((value or "").split())
        if not cleaned:
            return ""
        lowered = cleaned.lower()
        for token in (" table of contents", " index to", " index of", " index"):
            if lowered.endswith(token):
                cleaned = cleaned[: -len(token)].strip()
                lowered = cleaned.lower()
        if " index to " in lowered:
            cleaned = cleaned[: lowered.index(" index to ")].strip()
            lowered = cleaned.lower()
        if " table of contents" in lowered and lowered.endswith(" table of contents"):
            cleaned = cleaned[: lowered.index(" table of contents")].strip()
        return " ".join(cleaned.split())

    def company_name_from_markdown(self, *, path: Path) -> str | None:
        try:
            text = read_text_file(path=path, max_bytes=200_000)
        except Exception:  # noqa: BLE001 - best-effort extraction
            return None

        best: tuple[int, str] | None = None
        for line in text.splitlines()[:80]:
            ln = line.strip()
            if not ln.startswith("#"):
                continue
            level = len(ln) - len(ln.lstrip("#"))
            ln = ln.lstrip("#").strip()
            if not ln:
                continue
            ln = self.strip_md_emphasis(ln)
            ln = self.clean_company_heading(ln)
            if not ln:
                continue

            lowered = ln.lower()
            if lowered in {"table of contents", "index", "index to", "index of"}:
                continue
            if "table of contents" in lowered:
                continue

            score = 0
            if level == 1:
                score += 3
            if " form " in lowered or lowered.endswith(" form") or lowered.startswith("form "):
                score += 6
                parts = ln.split(" Form ", 1)
                if len(parts) == 2 and parts[0].strip():
                    ln = parts[0].strip()
                else:
                    parts = ln.split(" FORM ", 1)
                    if len(parts) == 2 and parts[0].strip():
                        ln = parts[0].strip()
            if any(t in lowered for t in (" corporation", " corp", " inc", " ltd", " limited", " plc", " company")):
                score += 2
            if " index" in lowered:
                score -= 4

            ln = self.clean_company_heading(ln)
            if not ln:
                continue
            if best is None or score > best[0]:
                best = (score, ln)

        if best and best[1]:
            return best[1]
        return None

    def resolve_company_name(self, *, ticker: str, md_path: Path) -> str:
        use_yahoo = self.env_bool("FINRAG_INGESTED_COMPANIES_USE_YAHOO", default=True)
        if use_yahoo:
            if self.yahoo_company_resolver is None:
                try:
                    from finrag.chunk_postprocess import YahooFinanceCompanyNameResolver

                    self.yahoo_company_resolver = YahooFinanceCompanyNameResolver()
                except Exception:  # noqa: BLE001 - best-effort resolver
                    self.yahoo_company_resolver = False
            if self.yahoo_company_resolver is not False:
                try:
                    name = self.yahoo_company_resolver.resolve(ticker=ticker, cik=None)  # type: ignore[union-attr]
                except Exception:  # noqa: BLE001 - best-effort resolver
                    name = None
                if isinstance(name, str) and name.strip() and not self.looks_like_junk_company_name(name):
                    return name.strip()

        md_name = self.company_name_from_markdown(path=md_path)
        if isinstance(md_name, str) and md_name.strip() and not self.looks_like_junk_company_name(md_name):
            return md_name.strip()
        return ticker

    @staticmethod
    def looks_like_junk_company_name(name: str) -> bool:
        cleaned = " ".join((name or "").split()).strip()
        if not cleaned:
            return True
        lowered = cleaned.lower()
        if lowered in {"table of contents", "index", "index to", "index of"}:
            return True
        if "table of contents" in lowered:
            return True
        if lowered.startswith("index ") or " index to " in lowered:
            return True
        return False

    @staticmethod
    def env_bool(name: str, default: bool = False) -> bool:
        value = os.getenv(name)
        if value is None:
            return default
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
