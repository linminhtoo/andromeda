from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.fixture(autouse=True)
def _test_env_safety(monkeypatch: pytest.MonkeyPatch) -> None:
    # Keep tests from mutating repo state or enabling noisy tracing by default.
    monkeypatch.setenv("DISABLE_HISTORY", os.getenv("DISABLE_HISTORY", "true"))
    monkeypatch.setenv("FINRAG_OTEL_ENABLED", os.getenv("FINRAG_OTEL_ENABLED", "false"))
    monkeypatch.setenv("TOKENIZERS_PARALLELISM", os.getenv("TOKENIZERS_PARALLELISM", "false"))
