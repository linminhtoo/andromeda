from __future__ import annotations

import random

import numpy as np
import pytest

from finrag.utils import get_env_var, seed_everything


def test_get_env_var_returns_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINRAG_TEST_ENV", "hello")
    assert get_env_var("FINRAG_TEST_ENV") == "hello"


def test_get_env_var_raises_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FINRAG_TEST_MISSING", raising=False)
    with pytest.raises(RuntimeError, match=r"FINRAG_TEST_MISSING"):
        get_env_var("FINRAG_TEST_MISSING")


def test_seed_everything_makes_random_and_numpy_deterministic() -> None:
    seed_everything(123)
    r1 = random.random()
    n1 = float(np.random.rand())

    seed_everything(123)
    r2 = random.random()
    n2 = float(np.random.rand())

    assert r1 == r2
    assert n1 == n2
