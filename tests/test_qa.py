from __future__ import annotations

import pytest

from finrag.dataclasses import DocChunk, ScoredChunk
from finrag.qa import answer_question_two_stage, build_context, build_draft_prompt, build_refine_prompt
from tests.fakes import RecordingLLM


def test_build_context_uses_retrieval_text_and_context_metadata_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTEXT_METADATA_KEY", "ctx")
    chunks = [
        ScoredChunk(
            chunk=DocChunk(
                id="c1",
                doc_id="doc1",
                text="RAW1",
                page_no=None,
                headings=[],
                source="s",
                metadata={"retrieval_text": "IDX1", "ctx": "C1"},
            ),
            score=1.0,
            source="hybrid",
        ),
        ScoredChunk(
            chunk=DocChunk(
                id="c2",
                doc_id="doc2",
                text="RAW2",
                page_no=None,
                headings=[],
                source="s",
                metadata={"retrieval_text": "IDX2"},
            ),
            score=0.5,
            source="hybrid",
        ),
    ]

    out = build_context(chunks, max_tokens=10_000)
    assert "[doc=doc1]" in out
    assert "IDX1" in out
    assert "RAW1" not in out
    assert "Context:\nC1" in out
    assert "[doc=doc2]" in out
    assert "IDX2" in out


def test_build_context_respects_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CONTEXT_METADATA_KEY", raising=False)
    chunks = [
        ScoredChunk(
            chunk=DocChunk(id="c1", doc_id="doc1", text="short", page_no=None, headings=[], source="s"),
            score=1.0,
            source="hybrid",
        ),
        ScoredChunk(
            chunk=DocChunk(id="c2", doc_id="doc2", text="X" * 400, page_no=None, headings=[], source="s"),
            score=0.5,
            source="hybrid",
        ),
    ]
    out = build_context(chunks, max_tokens=30)  # ~120 chars
    assert "[doc=doc1]" in out
    assert "[doc=doc2]" not in out


def test_build_draft_and_refine_prompts_include_question_and_context() -> None:
    reranked = [
        ScoredChunk(
            chunk=DocChunk(id="c1", doc_id="doc1", text="t", page_no=None, headings=[], source="s"),
            score=1.0,
            source="hybrid",
        )
    ]

    draft = build_draft_prompt("Q?", reranked, draft_max_tokens=100, answer_style="concise", system_extra="EXTRA")
    assert [m["role"] for m in draft] == ["system", "user"]
    assert "EXTRA" in draft[0]["content"]
    assert "Question:\nQ?" in draft[1]["content"]
    assert "Context:\n" in draft[1]["content"]

    refine = build_refine_prompt("Q?", "DRAFT", reranked, final_max_tokens=100, answer_style="normal")
    assert [m["role"] for m in refine] == ["system", "user"]
    assert "User question:\nQ?" in refine[1]["content"]
    assert "Draft answer:\nDRAFT" in refine[1]["content"]


def test_answer_question_two_stage_calls_llm_twice() -> None:
    outputs = ["draft1", "final1"]

    def chat_fn(_messages, _temp, _rm):
        return outputs.pop(0)

    llm = RecordingLLM(chat_fn=chat_fn)
    reranked = [
        ScoredChunk(
            chunk=DocChunk(id="c1", doc_id="doc1", text="t", page_no=None, headings=[], source="s"),
            score=1.0,
            source="hybrid",
        )
    ]
    draft, final = answer_question_two_stage(llm, "Q?", reranked, draft_max_tokens=50, final_max_tokens=50)
    assert (draft, final) == ("draft1", "final1")
    assert len(llm.chat_calls) == 2
