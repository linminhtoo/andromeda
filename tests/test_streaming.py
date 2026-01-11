from __future__ import annotations

import asyncio

from finrag.streaming import TextDeltaBatcher, _approx_tokens, iter_chat_deltas, ndjson_bytes
from tests.fakes import RecordingLLM


def test_approx_tokens() -> None:
    assert _approx_tokens("") == 0
    assert _approx_tokens("a") == 1
    assert _approx_tokens("abcd") == 1
    assert _approx_tokens("abcde") == 2


def test_ndjson_bytes_appends_newline() -> None:
    b = ndjson_bytes({"a": 1})
    assert b.endswith(b"\n")


def test_text_delta_batcher_flushes_by_chars() -> None:
    b = TextDeltaBatcher(flush_tokens=0, flush_chars=3, flush_interval_ms=0)
    b.add("ab")
    assert b.pop_ready() is None
    b.add("c")
    out = b.pop_ready()
    assert out == "abc"
    assert b.pop_ready() is None


def test_text_delta_batcher_flushes_by_tokens() -> None:
    b = TextDeltaBatcher(flush_tokens=2, flush_chars=0, flush_interval_ms=0)
    b.add("1234")  # ~1 token
    assert b.pop_ready() is None
    b.add("5")  # ~2 tokens total
    assert b.pop_ready() == "12345"


def test_iter_chat_deltas_falls_back_to_chat_when_no_stream() -> None:
    class ChatOnlyLLM:
        def chat(self, messages, temperature=0.1):
            _ = messages, temperature
            return "HELLO"

    async def collect() -> list[str]:
        out = []
        async for d in iter_chat_deltas(
            ChatOnlyLLM(),
            [{"role": "user", "content": "x"}],
            temperature=0.0,
            is_cancelled=lambda: False,
            set_cancelled=lambda: None,
            is_disconnected=lambda: False,
        ):
            out.append(d)
        return out

    assert asyncio.run(collect()) == ["HELLO"]


def test_iter_chat_deltas_streams_tokens() -> None:
    llm = RecordingLLM(stream_fn=lambda _m, _t, _rm: iter(["a", "b"]))

    async def collect() -> list[str]:
        out = []
        async for d in iter_chat_deltas(
            llm,
            [{"role": "user", "content": "x"}],
            temperature=0.0,
            is_cancelled=lambda: False,
            set_cancelled=lambda: None,
            is_disconnected=lambda: False,
        ):
            out.append(d)
        return out

    assert asyncio.run(collect()) == ["a", "b"]

