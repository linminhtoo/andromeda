from __future__ import annotations

import pytest
from fastapi import FastAPI

import finrag.telemetry as tel


def test_otel_exclude_spans_defaults_to_send_receive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FINRAG_OTEL_EXCLUDE_SPANS", raising=False)
    assert tel._otel_exclude_spans() == ["send", "receive"]


def test_otel_exclude_spans_empty_disables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINRAG_OTEL_EXCLUDE_SPANS", "")
    assert tel._otel_exclude_spans() is None


def test_otel_exclude_spans_filters_and_dedupes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINRAG_OTEL_EXCLUDE_SPANS", "receive,send,send,wat")
    assert tel._otel_exclude_spans() == ["receive", "send"]


def test_setup_opentelemetry_is_noop_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    # Guard: should not attempt to instrument when disabled.
    monkeypatch.setenv("FINRAG_OTEL_ENABLED", "false")

    class DummyInstr:
        @staticmethod
        def instrument_app(*_args, **_kwargs):
            raise AssertionError("instrument_app should not be called when FINRAG_OTEL_ENABLED=false")

    monkeypatch.setattr(tel, "FastAPIInstrumentor", DummyInstr)
    tel.setup_opentelemetry(FastAPI())
