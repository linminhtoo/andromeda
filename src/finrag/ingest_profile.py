from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now_utc_iso() -> str:
    """
    Return current UTC timestamp in ISO-8601 format.
    """

    return datetime.now(timezone.utc).isoformat()


def sanitize_ingest_profile_name(value: str) -> str:
    """
    Return filesystem-safe ingest profile name.
    """

    raw = str(value or "").strip()
    if not raw:
        return "default"

    chars: list[str] = []
    for ch in raw:
        if ch.isalnum() or ch in {"-", "_", "."}:
            chars.append(ch)
        else:
            chars.append("_")

    candidate = "".join(chars).strip("._-")
    if not candidate:
        return "default"
    return candidate


def resolve_ingest_profile_name(explicit: str | None = None) -> str:
    """
    Resolve profile name from explicit value or environment.

    Resolution order:
    1. explicit argument
    2. FINRAG_INGEST_PROFILE
    3. POSTGRES_SCHEMA
    4. default
    """

    if explicit and explicit.strip():
        return sanitize_ingest_profile_name(explicit)

    env_profile = (os.getenv("FINRAG_INGEST_PROFILE") or "").strip()
    if env_profile:
        return sanitize_ingest_profile_name(env_profile)

    env_schema = (os.getenv("POSTGRES_SCHEMA") or "").strip()
    if env_schema:
        return sanitize_ingest_profile_name(env_schema)

    return "default"


def ingest_profile_dir(project_root: Path, root_override: str | Path | None = None) -> Path:
    """
    Return directory where ingest profile JSON files are stored.
    """

    override = root_override
    if override is None:
        from_env = (os.getenv("FINRAG_INGEST_PROFILE_DIR") or "").strip()
        if from_env:
            override = from_env

    if override is None:
        return (project_root / "data" / "ingest_profiles").resolve()

    path = Path(os.path.expanduser(str(override)))
    if path.is_absolute():
        return path.resolve()
    return (project_root / path).resolve()


def ingest_profile_path(
    project_root: Path,
    profile_name: str,
    root_override: str | Path | None = None,
) -> Path:
    """
    Return JSON file path for an ingest profile.
    """

    safe_name = sanitize_ingest_profile_name(profile_name)
    return ingest_profile_dir(project_root, root_override=root_override) / f"{safe_name}.json"


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, set):
        return sorted(str(item) for item in value)
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()  # type: ignore[no-any-return]
        except Exception:  # noqa: BLE001
            pass
    return str(value)


def load_ingest_profile(
    project_root: Path,
    profile_name: str,
    root_override: str | Path | None = None,
) -> dict[str, Any]:
    """
    Load ingest profile JSON; return empty dict when absent/invalid.
    """

    path = ingest_profile_path(project_root, profile_name, root_override=root_override)
    if not path.exists() or not path.is_file():
        return {}

    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}

    if not isinstance(parsed, dict):
        return {}
    return parsed


def ingest_profile_step_settings(profile: dict[str, Any], step_name: str) -> dict[str, Any]:
    """
    Return settings payload for a given step from profile.
    """

    if "steps" not in profile:
        return {}
    steps_obj = profile["steps"]
    if not isinstance(steps_obj, dict):
        return {}
    if step_name not in steps_obj:
        return {}
    step_obj = steps_obj[step_name]
    if not isinstance(step_obj, dict):
        return {}
    if "settings" not in step_obj:
        return {}
    settings_obj = step_obj["settings"]
    if not isinstance(settings_obj, dict):
        return {}
    return dict(settings_obj)


def update_ingest_profile_step(
    *,
    project_root: Path,
    profile_name: str,
    step_name: str,
    settings: dict[str, Any],
    metadata: dict[str, Any] | None = None,
    root_override: str | Path | None = None,
) -> Path:
    """
    Upsert one step's settings in an ingest profile JSON file.
    """

    safe_name = sanitize_ingest_profile_name(profile_name)
    path = ingest_profile_path(project_root, safe_name, root_override=root_override)
    payload = load_ingest_profile(project_root, safe_name, root_override=root_override)
    now = now_utc_iso()

    if "created_at" not in payload:
        payload["created_at"] = now
    payload["updated_at"] = now
    payload["profile_name"] = safe_name

    if "steps" not in payload or not isinstance(payload["steps"], dict):
        payload["steps"] = {}

    steps_obj = payload["steps"]
    assert isinstance(steps_obj, dict)

    step_payload: dict[str, Any] = {
        "updated_at": now,
        "settings": settings,
    }
    if metadata is not None:
        step_payload["metadata"] = metadata

    steps_obj[step_name] = step_payload

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")
    return path
