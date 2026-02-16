from __future__ import annotations

import pytest

import andromeda.context_support as cs
from andromeda.dataclasses import DocChunk
from tests.fakes import RecordingLLM


def test_situate_context_returns_empty_when_missing_inputs() -> None:
    llm = RecordingLLM()
    assert cs.situate_context(llm, context="", chunk="x") == ""
    assert cs.situate_context(llm, context="x", chunk="") == ""
    assert llm.chat_calls == []


def test_situate_context_truncates_and_calls_llm() -> None:
    def chat_fn(messages, temperature, response_model):
        _ = temperature, response_model
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        prompt = messages[1]["content"]
        assert "[TRUNCATED]" in prompt
        return "  situated  "

    llm = RecordingLLM(chat_fn=chat_fn)
    out = cs.situate_context(llm, context="c" * 50, chunk="k" * 50, max_context_chars=10, max_chunk_chars=10)
    assert out == "situated"
    assert llm.chat_calls[0]["max_tokens"] == 256


def test_apply_context_strategy_neighbors_sets_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, str]] = []

    def fake_situate(_llm, *, context: str, chunk: str, temperature: float = 0.0, **_kwargs) -> str:
        calls.append({"context": context, "chunk": chunk})
        return f"ctx:{chunk}"

    monkeypatch.setattr(cs, "situate_context", fake_situate)

    chunks = [
        DocChunk(id="c1", doc_id="d", text="t1", page_no=None, headings=[], source="s", metadata={}),
        DocChunk(id="c2", doc_id="d", text="t2", page_no=None, headings=[], source="s", metadata={"context": "keep"}),
        DocChunk(id="c3", doc_id="d", text="t3", page_no=None, headings=[], source="s", metadata={}),
    ]
    llm = RecordingLLM()
    cs.apply_context_strategy(
        chunks,
        strategy="neighbors",
        neighbor_window=1,
        llm_for_context=llm,
        metadata_key="context",
        max_concurrency=2,
        skip_if_exists=True,
    )

    assert chunks[0].metadata and chunks[0].metadata["context"] == "ctx:t1"
    assert chunks[1].metadata and chunks[1].metadata["context"] == "keep"
    assert chunks[2].metadata and chunks[2].metadata["context"] == "ctx:t3"

    # Only c1 and c3 were processed (c2 skipped).
    assert {c["chunk"] for c in calls} == {"t1", "t3"}
    # Neighbor context for c1 includes next chunk.
    ctx_by_chunk = {c["chunk"]: c["context"] for c in calls}
    assert "AFTER this chunk:" in ctx_by_chunk["t1"]
    assert "t2" in ctx_by_chunk["t1"]


def test_apply_context_strategy_document_uses_joined_doc_text(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def fake_situate(_llm, *, context: str, chunk: str, temperature: float = 0.0, **_kwargs) -> str:
        _ = temperature
        # Full doc text should include all chunks.
        assert "alpha" in context and "beta" in context
        seen.append(chunk)
        return "ok"

    monkeypatch.setattr(cs, "situate_context", fake_situate)

    chunks = [
        DocChunk(id="c1", doc_id="d", text="alpha", page_no=None, headings=[], source="s", metadata={}),
        DocChunk(id="c2", doc_id="d", text="beta", page_no=None, headings=[], source="s", metadata={}),
    ]
    cs.apply_context_strategy(chunks, strategy="document", llm_for_context=RecordingLLM(), metadata_key="ctx")
    assert set(seen) == {"alpha", "beta"}
    assert all((ch.metadata or {}).get("ctx") == "ok" for ch in chunks)


def test_apply_context_strategy_metadata_and_none_are_noops() -> None:
    chunks = [DocChunk(id="c1", doc_id="d", text="t", page_no=None, headings=[], source="s", metadata={})]
    cs.apply_context_strategy(chunks, strategy="metadata", llm_for_context=None)
    cs.apply_context_strategy(chunks, strategy="none", llm_for_context=None)
    assert chunks[0].metadata == {}


def test_apply_context_strategy_unknown_raises() -> None:
    chunks = [DocChunk(id="c1", doc_id="d", text="t", page_no=None, headings=[], source="s", metadata={})]
    with pytest.raises(ValueError, match="Unknown context strategy"):
        cs.apply_context_strategy(chunks, strategy="nope", llm_for_context=RecordingLLM())
