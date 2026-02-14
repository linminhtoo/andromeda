from __future__ import annotations

from pathlib import Path

import pytest

from finrag.ingestion_jobs import (
    TickerIngestionRuntimeConfig,
    build_chunk_command,
    build_download_command,
    build_index_command,
    normalize_ticker,
)


def make_config(**overrides: object) -> TickerIngestionRuntimeConfig:
    values = {
        "postgres_dsn": "postgresql://user:pass@localhost:5432/db",
        "postgres_schema": "exp_finrag",
        "sparse_search_method": "bm25",
        "llm_provider": "openai",
        "dense_model": "BAAI/bge-m3",
        "dense_base_url": "http://localhost:8001/v1",
        "contextual_llm_provider": "openai",
        "contextual_model": "Qwen/Qwen3-VL-32B-Instruct-FP8",
        "contextual_base_url": "http://localhost:8002/v1",
        "context_strategy": "neighbors",
        "context_window": 1,
        "context_metadata_key": "retrieval_context",
        "context_max_tokens": 256,
        "context_max_concurrency": 64,
        "batch_size": 128,
        "ingest_profile": "exp_finrag",
        "download_delay": 0.2,
        "download_skip_existing": True,
        "process_parser_mode": "auto",
        "process_recursive": True,
        "process_continue_on_error": True,
        "chunker": "markdown_table_preserving",
        "chunk_max_tokens": 1024,
        "chunk_overlap_tokens": 128,
        "chunk_recursive": True,
        "chunk_doc_id_strategy": "sha1_relpath",
        "chunk_split_markdown_tables": False,
    }
    values.update(overrides)
    return TickerIngestionRuntimeConfig(**values)


def test_normalize_ticker_accepts_expected_symbols() -> None:
    assert normalize_ticker(" amd ") == "AMD"
    assert normalize_ticker("BRK.B") == "BRK.B"
    assert normalize_ticker("ABC-1") == "ABC-1"


def test_normalize_ticker_rejects_invalid_symbols() -> None:
    with pytest.raises(ValueError, match="Ticker must contain only"):
        normalize_ticker("AMD$")


def test_build_index_command_includes_runtime_compatibility_args() -> None:
    cfg = make_config()
    cmd = build_index_command(config=cfg, ingest_output_dir=Path("/tmp/chunked"))

    assert "--postgres-dsn" in cmd
    assert "--postgres-schema" in cmd
    assert "exp_finrag" in cmd
    assert "--sparse-search-method" in cmd
    assert "bm25" in cmd

    assert "--context" in cmd
    assert "neighbors" in cmd
    assert "--context-window" in cmd
    assert "1" in cmd
    assert "--context-metadata-key" in cmd
    assert "retrieval_context" in cmd
    assert "--contextual-model" in cmd
    assert "Qwen/Qwen3-VL-32B-Instruct-FP8" in cmd

    assert "--llm-provider" in cmd
    assert "openai" in cmd
    assert "--dense-model" in cmd
    assert "BAAI/bge-m3" in cmd
    assert "--ingest-profile" in cmd
    assert "exp_finrag" in cmd


def test_build_index_command_omits_optional_args_when_not_set() -> None:
    cfg = make_config(
        postgres_schema=None,
        llm_provider=None,
        dense_base_url=None,
        contextual_llm_provider=None,
        contextual_model=None,
        contextual_base_url=None,
    )
    cmd = build_index_command(config=cfg, ingest_output_dir=Path("/tmp/chunked"))

    assert "--postgres-schema" not in cmd
    assert "--llm-provider" not in cmd
    assert "--dense-base-url" not in cmd
    assert "--contextual-llm-provider" not in cmd
    assert "--contextual-model" not in cmd
    assert "--contextual-base-url" not in cmd


def test_build_download_command_supports_multiple_tickers() -> None:
    cmd = build_download_command(
        tickers=["AMD", "NVDA"],
        per_company=5,
        output_dir=Path("/tmp/download"),
        delay=0.5,
        skip_existing=True,
        ingest_profile="exp_finrag",
    )

    assert "--tickers" in cmd
    assert "AMD" in cmd
    assert "NVDA" in cmd
    assert "--delay" in cmd
    assert "0.5" in cmd
    assert "--skip-existing" in cmd
    assert "--ingest-profile" in cmd
    assert "exp_finrag" in cmd


def test_build_chunk_command_uses_runtime_chunk_settings() -> None:
    cmd = build_chunk_command(
        markdown_dir=Path("/tmp/md"),
        metadata_dir=Path("/tmp/debug"),
        output_dir=Path("/tmp/chunked"),
        chunker="markdown_table_preserving",
        max_tokens=2048,
        overlap_tokens=256,
        recursive=True,
        doc_id_strategy="sha1_relpath",
        split_markdown_tables=True,
        ingest_profile="exp_finrag",
    )

    assert "--max-tokens" in cmd
    assert "2048" in cmd
    assert "--overlap-tokens" in cmd
    assert "256" in cmd
    assert "--split-markdown-tables" in cmd
