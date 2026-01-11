from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from pydantic import BaseModel

from finrag.llm_clients import ChatMessage


EmbedFn = Callable[[list[str]], np.ndarray]
ChatFn = Callable[[list[ChatMessage], float, type[BaseModel] | None], str]
StreamFn = Callable[[list[ChatMessage], float, type[BaseModel] | None], Iterator[str]]


def keyword_count_embed(texts: list[str], *, keywords: list[str]) -> np.ndarray:
    keys = [k.casefold() for k in keywords]
    vecs: list[np.ndarray] = []
    for t in texts:
        t_cf = (t or "").casefold()
        counts = [float(t_cf.count(k)) for k in keys]
        vecs.append(np.asarray(counts, dtype=np.float32))
    return np.vstack(vecs) if vecs else np.zeros((0, len(keys)), dtype=np.float32)


@dataclass
class RecordingLLM:
    """
    Small in-memory fake for `finrag.llm_clients.LLMClient`.

    - Records `chat()` and `chat_stream()` calls for assertions.
    - `embed_texts()` uses a caller-supplied embedding function.
    """

    chat_model: str = "fake-chat"
    embed_model: str = "fake-embed"

    embed_fn: EmbedFn | None = None
    chat_fn: ChatFn | None = None
    stream_fn: StreamFn | None = None

    chat_calls: list[dict[str, Any]] = field(default_factory=list)
    chat_stream_calls: list[dict[str, Any]] = field(default_factory=list)

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        if self.embed_fn is None:
            # Default: 1D embedding = character length.
            return np.asarray([[float(len(t or ""))] for t in texts], dtype=np.float32)
        return self.embed_fn(texts)

    def chat(self, messages: list[ChatMessage], temperature: float = 0.1, response_model: type[BaseModel] | None = None) -> str:
        self.chat_calls.append({"messages": list(messages), "temperature": float(temperature), "response_model": response_model})
        if self.chat_fn is None:
            return "OK"
        return self.chat_fn(messages, float(temperature), response_model)

    def chat_stream(
        self, messages: list[ChatMessage], temperature: float = 0.1, response_model: type[BaseModel] | None = None
    ) -> Iterator[str]:
        self.chat_stream_calls.append(
            {"messages": list(messages), "temperature": float(temperature), "response_model": response_model}
        )
        if self.stream_fn is None:
            yield "O"
            yield "K"
            return
        yield from self.stream_fn(messages, float(temperature), response_model)

