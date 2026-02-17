import json
import math
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi.encoders import jsonable_encoder
from loguru import logger
from pydantic import BaseModel, Field

from andromeda.query.runtime import QueryRequest, QueryResponse


class HistoryEntry(BaseModel):
    id: str
    created_at: str
    request: QueryRequest
    response: QueryResponse
    timing_ms: dict[str, float] = Field(default_factory=dict)


class QueryHistoryStore:
    """
    Persist and query `/query` history entries in JSONL format.
    """

    def __init__(self, *, project_root: Path):
        self.project_root = project_root

    def path(self) -> Path:
        raw = os.getenv("HISTORY_PATH")
        if raw and raw.strip():
            return Path(os.path.expanduser(raw.strip())).resolve()
        return (self.project_root / "data" / "qa_history.jsonl").resolve()

    def append(self, *, req: QueryRequest, res: QueryResponse, timing_ms: dict[str, float] | None = None) -> None:
        if self._env_bool("DISABLE_HISTORY", default=False):
            return

        entry = HistoryEntry(
            id=str(uuid.uuid4()),
            created_at=datetime.now(timezone.utc).isoformat(),
            request=req,
            response=res,
            timing_ms=self._sanitize_timing_ms(timing_ms),
        )
        path = self.path()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(jsonable_encoder(entry), ensure_ascii=False) + "\n")
        except Exception as exc:  # noqa: BLE001 - history should never break /query
            logger.warning("Failed to write history to %s: %r", path, exc)

    def read(self, *, limit: int = 50, summary: bool = False) -> list[dict]:
        limit = max(0, int(limit))
        path = self.path()
        if limit == 0 or not path.exists():
            return []
        try:
            with path.open("r", encoding="utf-8") as f:
                lines = [ln for ln in (line.strip() for line in f) if ln]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to read history from %s: %r", path, exc)
            return []

        out: list[dict] = []
        for line in reversed(lines[-limit:]):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            try:
                entry = HistoryEntry.model_validate(payload)
            except Exception:  # noqa: BLE001
                continue
            if not summary:
                out.append(entry.model_dump())
                continue

            out.append(
                {
                    "id": entry.id,
                    "created_at": entry.created_at,
                    "request": {"question": entry.request.question, "mode": entry.request.mode},
                    "response": {"top_chunks_count": len(entry.response.top_chunks)},
                    "timing_ms": entry.timing_ms,
                }
            )
        return out

    def read_entry(self, *, entry_id: str) -> dict | None:
        want = (entry_id or "").strip()
        if not want:
            return None
        path = self.path()
        if not path.exists():
            return None

        try:
            with path.open("r", encoding="utf-8") as f:
                lines = [ln for ln in (line.strip() for line in f) if ln]
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Failed to read history: {exc}") from exc

        for line in reversed(lines):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            try:
                entry = HistoryEntry.model_validate(payload)
            except Exception:  # noqa: BLE001
                continue
            if entry.id == want:
                return entry.model_dump()
        return None

    def clear(self) -> Path:
        path = self.path()
        if path.exists():
            path.unlink()
        return path

    @staticmethod
    def _env_bool(name: str, default: bool = False) -> bool:
        value = os.getenv(name)
        if value is None:
            return default
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}

    @staticmethod
    def _sanitize_timing_ms(timing_ms: dict[str, float] | None) -> dict[str, float]:
        if not timing_ms:
            return {}
        out: dict[str, float] = {}
        for key, value in timing_ms.items():
            k = str(key or "").strip()
            if not k:
                continue
            try:
                n = float(value)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(n) or n < 0:
                continue
            out[k] = n
        return out
