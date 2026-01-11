from __future__ import annotations

import pytest
from pydantic import BaseModel

import finrag.llm_clients as lc


class _ToyModel(BaseModel):
    x: int


def test_build_response_format_openai_shape() -> None:
    rf = lc._build_response_format(provider="openai", response_model=_ToyModel)
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["name"] == "_ToyModel"
    assert "schema" in rf["json_schema"]


def test_build_response_format_mistral_shape() -> None:
    rf = lc._build_response_format(provider="mistral", response_model=_ToyModel)
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["name"] == "_ToyModel"
    assert "schema_definition" in rf["json_schema"]


def test_get_llm_client_rejects_langsmith_for_non_openai() -> None:
    with pytest.raises(ValueError, match="only supported for OpenAI"):
        lc.get_llm_client(provider="mistral", langsmith_trace=True)


def test_get_llm_client_rejects_unknown_provider() -> None:
    with pytest.raises(ValueError, match="Unsupported LLM provider"):
        lc.get_llm_client(provider="nope")


def test_get_llm_client_selects_wrappers(monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyOpenAI:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.chat_model = "x"
            self.embed_model = "y"

    class DummyMistral:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.chat_model = "x"
            self.embed_model = "y"

    monkeypatch.setattr(lc, "OpenAIClientWrapper", DummyOpenAI)
    monkeypatch.setattr(lc, "MistralClientWrapper", DummyMistral)

    out = lc.get_llm_client(provider="openai", base_url="http://example", chat_model="m")
    assert isinstance(out, DummyOpenAI)
    assert out.kwargs["base_url"] == "http://example"
    assert out.kwargs["chat_model"] == "m"

    out2 = lc.get_llm_client(provider="mistral", chat_model="m2")
    assert isinstance(out2, DummyMistral)
    assert out2.kwargs["chat_model"] == "m2"

