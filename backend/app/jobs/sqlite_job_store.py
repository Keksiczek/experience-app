"""Persistent job store backed by SQLite.

Replaces InMemoryJobStore as the production default.
Jobs survive process restarts and are queryable via GET /experiences/{id}.

TTL eviction runs on every save() call and removes records older than
settings.job_store_ttl_days (default: 7 days).
"""

import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger
from app.jobs.job_store import BaseJobStore
from app.models.experience import Experience

logger = get_logger(__name__)

# TODO: migrate to aiosqlite for true async I/O when request volume grows.
# asyncio.to_thread() is sufficient for Iteration 1 workloads.


class SQLiteJobStore(BaseJobStore):
    def __init__(self) -> None:
        self._db_path = settings.job_store_path
        self._ttl_days = settings.job_store_ttl_days
        self._init_db()

    def _init_db(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id      TEXT PRIMARY KEY,
                    data        TEXT NOT NULL,
                    created_at  TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_created_at ON jobs (created_at)")
            conn.commit()
        logger.info("sqlite_job_store_ready", path=self._db_path, ttl_days=self._ttl_days)

    # ── async public interface ────────────────────────────────────────────────

    async def save(self, experience: Experience) -> None:
        await asyncio.to_thread(self._save_sync, experience)

    async def get(self, job_id: str) -> Experience | None:
        return await asyncio.to_thread(self._get_sync, job_id)

    async def list_ids(self) -> list[str]:
        return await asyncio.to_thread(self._list_ids_sync)

    async def delete(self, job_id: str) -> bool:
        return await asyncio.to_thread(self._delete_sync, job_id)

    # ── sync helpers (called via to_thread) ──────────────────────────────────

    def _save_sync(self, experience: Experience) -> None:
        self._evict_old()
        data = experience.model_dump_json()
        now = datetime.now(UTC).isoformat()
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO jobs (job_id, data, created_at) VALUES (?, ?, ?)",
                (experience.id, data, now),
            )
            conn.commit()

    def _get_sync(self, job_id: str) -> Experience | None:
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT data FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        if row is None:
            return None
        return Experience.model_validate_json(row[0])

    def _list_ids_sync(self) -> list[str]:
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                "SELECT job_id FROM jobs ORDER BY created_at DESC"
            ).fetchall()
        return [row[0] for row in rows]

    def _delete_sync(self, job_id: str) -> bool:
        with sqlite3.connect(self._db_path) as conn:
            deleted = conn.execute(
                "DELETE FROM jobs WHERE job_id = ?", (job_id,)
            ).rowcount
            conn.commit()
        return deleted > 0

    def _evict_old(self) -> None:
        cutoff = (datetime.now(UTC) - timedelta(days=self._ttl_days)).isoformat()
        with sqlite3.connect(self._db_path) as conn:
            deleted = conn.execute(
                "DELETE FROM jobs WHERE created_at < ?", (cutoff,)
            ).rowcount
            conn.commit()
        if deleted:
            logger.info("sqlite_evicted_old_jobs", count=deleted, ttl_days=self._ttl_days)
