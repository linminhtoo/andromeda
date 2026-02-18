from __future__ import annotations

import pytest

from andromeda.llm.generation_controls import (
    AnsweringEffort,
    default_mode,
    get_preset,
    list_generation_presets,
    resolve_generation_settings,
)


def test_list_generation_presets_contains_expected_modes() -> None:
    keys = {p.key for p in list_generation_presets()}
    assert {"quick", "normal", "thinking"} <= keys


def test_default_mode_uses_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINRAG_DEFAULT_MODE", " thinking ")
    assert default_mode() == "thinking"

    monkeypatch.setenv("FINRAG_DEFAULT_MODE", "  ")
    assert default_mode() == "normal"


def test_get_preset_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINRAG_DEFAULT_MODE", "quick")
    assert get_preset("does-not-exist").key == "quick"


def test_resolve_generation_settings_caps_rerank_at_retrieve() -> None:
    s = resolve_generation_settings(mode="normal", top_k_retrieve=5, top_k_rerank=999)
    assert s.top_k_retrieve == 5
    assert s.top_k_rerank == 5


def test_resolve_generation_settings_pos_int_fallback() -> None:
    s = resolve_generation_settings(mode="quick", top_k_retrieve=-1, draft_max_tokens=0, final_max_tokens=None)
    # Falls back to preset values when invalid.
    assert s.top_k_retrieve > 0
    assert s.draft_max_tokens > 0
    assert s.final_max_tokens > 0


def test_resolve_generation_settings_allows_boolean_overrides() -> None:
    s = resolve_generation_settings(mode="quick", enable_rerank=True, enable_refine=True)
    assert s.enable_rerank is True
    assert s.enable_refine is True


def test_resolve_generation_settings_parses_effort_and_brief_budget() -> None:
    s = resolve_generation_settings(mode="normal", brief_max_tokens=7777, answering_effort="high")
    assert s.brief_max_tokens == 7777
    assert s.answering_effort == AnsweringEffort.HIGH
