from __future__ import annotations

import base64

import pytest

import finrag.ocr as ocrmod


def test_document_payload_from_source_url(monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyMistral:
        def __init__(self, api_key: str):
            self.api_key = api_key

    monkeypatch.setattr(ocrmod, "Mistral", DummyMistral)
    c = ocrmod.MistralOCRClient(api_key="test")
    payload = c._document_payload_from_source("https://example.com/doc.pdf")
    assert payload["type"] == "document_url"
    assert payload["document_url"] == "https://example.com/doc.pdf"


def test_document_payload_from_source_local_file(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    class DummyMistral:
        def __init__(self, api_key: str):
            self.api_key = api_key

    monkeypatch.setattr(ocrmod, "Mistral", DummyMistral)

    p = tmp_path / "x.pdf"
    p.write_bytes(b"not really a pdf")

    c = ocrmod.MistralOCRClient(api_key="test")
    payload = c._document_payload_from_source(str(p))
    assert payload["type"] == "document_url"
    url = payload["document_url"]
    assert isinstance(url, str)
    assert url.startswith("data:application/pdf;base64,")

    b64 = url.split(",", 1)[1]
    assert base64.b64decode(b64) == b"not really a pdf"


def test_pdf_to_markdown_joins_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyMistral:
        def __init__(self, api_key: str):
            self.api_key = api_key

    monkeypatch.setattr(ocrmod, "Mistral", DummyMistral)

    c = ocrmod.MistralOCRClient(api_key="test")
    monkeypatch.setattr(c, "pdf_to_markdown_pages", lambda _src: ["p1", "p2"])
    assert c.pdf_to_markdown("whatever.pdf", page_separator="--") == "p1--p2"

