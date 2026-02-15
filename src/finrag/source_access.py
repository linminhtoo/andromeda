import mimetypes
import os
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse, RedirectResponse


def source_roots(*, project_root: Path) -> list[Path]:
    """
    Resolve allowlisted source roots for local file serving.
    """

    raw = os.getenv("SOURCE_ROOTS")
    if raw:
        parts = [p.strip() for p in raw.split(os.pathsep) if p.strip()]
        return [Path(p).expanduser().resolve() for p in parts]
    return [project_root, project_root / "data"]


def resolve_local_source(*, path: str, project_root: Path) -> Path:
    """
    Resolve a user-provided file path and enforce SOURCE_ROOTS allowlist.
    """

    source_path = (path or "").strip()
    if not source_path:
        raise HTTPException(status_code=400, detail="Missing `path`")

    local_path = Path(os.path.expanduser(source_path))
    if not local_path.is_absolute():
        local_path = (project_root / local_path).resolve()
    else:
        local_path = local_path.resolve()

    if not local_path.exists() or not local_path.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {local_path}")

    allowlisted_roots = source_roots(project_root=project_root)
    if not any(local_path == root or local_path.is_relative_to(root) for root in allowlisted_roots):
        raise HTTPException(
            status_code=403,
            detail=(
                "Path is outside SOURCE_ROOTS; set SOURCE_ROOTS to a colon-separated allowlist of directories."
            ),
        )

    return local_path


def read_text_file(*, path: Path, max_bytes: int) -> str:
    """
    Read UTF-8 text with a hard size limit.
    """

    if max_bytes <= 0:
        raise HTTPException(status_code=400, detail="SOURCE_TEXT_MAX_BYTES must be > 0")
    size = path.stat().st_size
    if size > max_bytes:
        raise HTTPException(status_code=413, detail=f"File too large ({size} bytes); max is {max_bytes} bytes")
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


def source_response(*, path: str, project_root: Path) -> RedirectResponse | FileResponse:
    """
    Build response for `/source` endpoint.
    """

    source_path = (path or "").strip()
    if source_path.startswith(("http://", "https://")):
        return RedirectResponse(url=source_path)
    local_path = resolve_local_source(path=source_path, project_root=project_root)
    media_type, _enc = mimetypes.guess_type(str(local_path))
    return FileResponse(
        path=local_path,
        media_type=media_type or "application/octet-stream",
        filename=local_path.name,
        content_disposition_type="inline",
    )
