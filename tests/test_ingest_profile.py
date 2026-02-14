from __future__ import annotations

from pathlib import Path

from finrag.ingest_profile import (
    ingest_profile_step_settings,
    load_ingest_profile,
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
