from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


def _as_str(value: object, *, strip: bool = True) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip() if strip else value


def _extras(mapping: Mapping[str, Any], *, known_keys: set[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in mapping.items():
        if key in known_keys:
            continue
        out[key] = value
    return out


@dataclass(frozen=True)
class DocumentMetadata:
    """
    Known document-level metadata fields attached to a chunk.
    """

    company: str | None = None
    ticker: str | None = None
    cik: str | None = None
    accession: str | None = None
    filing_type: str | None = None
    filing_date: str | None = None
    period_end_date: str | None = None
    filing_quarter: str | None = None
    filing_quarter_basis: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_value(cls, value: object) -> DocumentMetadata | None:
        """
        Parse arbitrary metadata into a typed document metadata object.
        """

        if not isinstance(value, Mapping):
            return None

        src = dict(value)
        known_keys = {
            "company",
            "ticker",
            "cik",
            "accession",
            "filing_type",
            "filing_date",
            "period_end_date",
            "filing_quarter",
            "filing_quarter_basis",
        }
        return cls(
            company=_as_str(src["company"]) if "company" in src else None,
            ticker=_as_str(src["ticker"]) if "ticker" in src else None,
            cik=_as_str(src["cik"]) if "cik" in src else None,
            accession=_as_str(src["accession"]) if "accession" in src else None,
            filing_type=_as_str(src["filing_type"]) if "filing_type" in src else None,
            filing_date=_as_str(src["filing_date"]) if "filing_date" in src else None,
            period_end_date=_as_str(src["period_end_date"]) if "period_end_date" in src else None,
            filing_quarter=_as_str(src["filing_quarter"]) if "filing_quarter" in src else None,
            filing_quarter_basis=_as_str(src["filing_quarter_basis"]) if "filing_quarter_basis" in src else None,
            extra=_extras(src, known_keys=known_keys),
        )

    def to_dict(self) -> dict[str, Any]:
        """
        Serialize the typed metadata into plain JSON-friendly mapping.
        """

        out: dict[str, Any] = dict(self.extra)
        if self.company is not None:
            out["company"] = self.company
        if self.ticker is not None:
            out["ticker"] = self.ticker
        if self.cik is not None:
            out["cik"] = self.cik
        if self.accession is not None:
            out["accession"] = self.accession
        if self.filing_type is not None:
            out["filing_type"] = self.filing_type
        if self.filing_date is not None:
            out["filing_date"] = self.filing_date
        if self.period_end_date is not None:
            out["period_end_date"] = self.period_end_date
        if self.filing_quarter is not None:
            out["filing_quarter"] = self.filing_quarter
        if self.filing_quarter_basis is not None:
            out["filing_quarter_basis"] = self.filing_quarter_basis
        return out


@dataclass(frozen=True)
class ChunkMetadata:
    """
    Known chunk-level metadata fields used by retrieval/QA/eval code.
    """

    doc: DocumentMetadata | None = None
    summary: str | None = None
    retrieval_text: str | None = None
    retrieval_context: str | None = None
    section_path: str | None = None
    block_type: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_value(cls, value: object) -> ChunkMetadata:
        """
        Parse arbitrary chunk metadata into a typed object.
        """

        if not isinstance(value, Mapping):
            return cls()

        src = dict(value)
        known_keys = {"doc", "summary", "retrieval_text", "retrieval_context", "section_path", "block_type"}
        doc_value = src["doc"] if "doc" in src else None

        return cls(
            doc=DocumentMetadata.from_value(doc_value),
            summary=_as_str(src["summary"]) if "summary" in src else None,
            retrieval_text=_as_str(src["retrieval_text"], strip=False) if "retrieval_text" in src else None,
            retrieval_context=_as_str(src["retrieval_context"], strip=False) if "retrieval_context" in src else None,
            section_path=_as_str(src["section_path"]) if "section_path" in src else None,
            block_type=_as_str(src["block_type"]) if "block_type" in src else None,
            extra=_extras(src, known_keys=known_keys),
        )

    def to_dict(self) -> dict[str, Any]:
        """
        Serialize typed metadata into plain mapping.
        """

        out: dict[str, Any] = dict(self.extra)
        if self.doc is not None:
            out["doc"] = self.doc.to_dict()
        if self.summary is not None:
            out["summary"] = self.summary
        if self.retrieval_text is not None:
            out["retrieval_text"] = self.retrieval_text
        if self.retrieval_context is not None:
            out["retrieval_context"] = self.retrieval_context
        if self.section_path is not None:
            out["section_path"] = self.section_path
        if self.block_type is not None:
            out["block_type"] = self.block_type
        return out

    def context_for_key(self, key: str) -> str | None:
        """
        Return context string by key, preferring typed fields.
        """

        if key == "retrieval_context":
            return self.retrieval_context
        if key == "retrieval_text":
            return self.retrieval_text
        if key not in self.extra:
            return None
        raw = self.extra[key]
        if isinstance(raw, str):
            return raw
        return str(raw) if raw is not None else None


def chunk_metadata_from_value(value: object) -> ChunkMetadata:
    """
    Convenience parser for chunk metadata values.
    """

    return ChunkMetadata.from_value(value)
