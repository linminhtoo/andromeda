from __future__ import annotations

from pathlib import Path

from andromeda.ingest_profile import (
    ingest_profile_layout,
    ingest_profile_step_settings,
    load_ingest_profile,
    postgres_schema_for_ingest_profile,
    resolve_ingest_profile_name,
    update_ingest_profile_step,
)


def test_resolve_ingest_profile_name_precedence(monkeypatch) -> None:
    monkeypatch.setenv("FINRAG_INGEST_PROFILE", "from_env_profile")
    monkeypatch.setenv("POSTGRES_SCHEMA", "from_schema")

    assert resolve_ingest_profile_name("explicit") == "explicit"
    assert resolve_ingest_profile_name(None) == "from_env_profile"

    monkeypatch.delenv("FINRAG_INGEST_PROFILE", raising=False)
    assert resolve_ingest_profile_name(None) == "from_schema"

    monkeypatch.delenv("POSTGRES_SCHEMA", raising=False)
    assert resolve_ingest_profile_name(None) == "default"


def test_update_and_load_ingest_profile_step(tmp_path: Path) -> None:
    project_root = tmp_path

    update_ingest_profile_step(
        project_root=project_root,
        profile_name="exp_ctx_neighbors",
        step_name="chunk",
        settings={"max_tokens": 1024, "overlap_tokens": 128},
        metadata={"output_dir": "/tmp/chunked"},
    )

    profile = load_ingest_profile(project_root=project_root, profile_name="exp_ctx_neighbors")
    chunk_settings = ingest_profile_step_settings(profile, "chunk")

    assert profile["profile_name"] == "exp_ctx_neighbors"
    assert chunk_settings["max_tokens"] == 1024
    assert chunk_settings["overlap_tokens"] == 128

    update_ingest_profile_step(
        project_root=project_root,
        profile_name="exp_ctx_neighbors",
        step_name="build_index",
        settings={"context": "neighbors", "context_window": 1},
    )

    profile2 = load_ingest_profile(project_root=project_root, profile_name="exp_ctx_neighbors")
    index_settings = ingest_profile_step_settings(profile2, "build_index")
    assert index_settings["context"] == "neighbors"
    assert index_settings["context_window"] == 1


def test_ingest_profile_layout_is_profile_scoped(tmp_path: Path) -> None:
    layout = ingest_profile_layout(project_root=tmp_path, profile_name="exp_ctx_neighbors")

    assert layout.profile_name == "exp_ctx_neighbors"
    assert layout.profile_root == (tmp_path / "data" / "ingest_profiles" / "exp_ctx_neighbors").resolve()
    assert layout.sec_filings_root == layout.profile_root / "sec_filings"
    assert layout.sec_filings_raw_html_dir == layout.sec_filings_root / "raw_htmls"
    assert layout.sec_filings_meta_dir == layout.sec_filings_root / "meta"
    assert layout.sec_filings_md_root == layout.profile_root / "sec_filings_md_secparser"
    assert layout.sec_filings_md_processed_dir == layout.sec_filings_md_root / "processed_markdown"
    assert layout.sec_filings_md_debug_dir == layout.sec_filings_md_root / "debug"
    assert (
        layout.chunk_output_dir(max_tokens=1024, overlap_tokens=128) == layout.sec_filings_md_root / "chunked_1024_128"
    )


def test_postgres_schema_for_ingest_profile_uses_sanitized_profile_name() -> None:
    assert postgres_schema_for_ingest_profile("exp ctx/neighbors") == "exp_ctx_neighbors"
