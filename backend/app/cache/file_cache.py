import gzip
import json
import time
from pathlib import Path
from typing import Any

from app.cache.base import BaseCache


class FileCache(BaseCache):
    """
    Simple file-based cache. Each entry is a gzip-compressed JSON file.
    Designed to be replaced with Redis in later iterations.
    """

    def __init__(self, cache_dir: str) -> None:
        self._dir = Path(cache_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        safe_key = key.replace("/", "_").replace(":", "_")
        return self._dir / f"{safe_key}.json.gz"

    async def get(self, key: str) -> Any | None:
        path = self._path(key)
        if not path.exists():
            return None

        try:
            with gzip.open(path, "rt", encoding="utf-8") as f:
                envelope = json.load(f)
        except (OSError, json.JSONDecodeError):
            return None

        if envelope.get("expires_at", 0) < time.time():
            path.unlink(missing_ok=True)
            return None

        return envelope.get("value")

    async def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        envelope = {
            "value": value,
            "expires_at": time.time() + ttl_seconds,
            "created_at": time.time(),
        }
        path = self._path(key)
        with gzip.open(path, "wt", encoding="utf-8") as f:
            json.dump(envelope, f)

    async def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    async def clear_expired(self) -> int:
        removed = 0
        now = time.time()
        for path in self._dir.glob("*.json.gz"):
            try:
                with gzip.open(path, "rt", encoding="utf-8") as f:
                    envelope = json.load(f)
                if envelope.get("expires_at", 0) < now:
                    path.unlink(missing_ok=True)
                    removed += 1
            except (OSError, json.JSONDecodeError):
                path.unlink(missing_ok=True)
                removed += 1
        return removed
