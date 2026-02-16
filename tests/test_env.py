from __future__ import annotations

from pathlib import Path

import pytest

import andromeda.env as envmod


def test_load_project_dotenv_calls_load_dotenv_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def fake_load_dotenv(*args: object, **kwargs: object) -> None:
        calls.append((args, kwargs))

    monkeypatch.setattr(envmod, "_DOTENV_LOADED", False)
    monkeypatch.setattr(envmod, "load_dotenv", fake_load_dotenv)

    assert envmod.load_project_dotenv(override=True) is True
    assert envmod.load_project_dotenv(override=True) is False
    assert len(calls) == 1

    args, kwargs = calls[0]
    assert kwargs.get("override") is True

    # If the repo has a root `.env`, we should pass its path explicitly.
    if args:
        assert len(args) == 1
        assert isinstance(args[0], Path)
        assert Path(args[0]).name == ".env"
