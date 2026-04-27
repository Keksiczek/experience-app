"""
Job store abstraction.

PERSISTENCE LIMITATIONS (first iteration):
    InMemoryJobStore holds all jobs in a process-local dict. This means:
    - All jobs are lost on process restart or crash.
    - Jobs cannot be queried from a second worker process.
    - There is no execution audit trail or resumability.
    - The store will grow unbounded in a long-running process.

    This is intentional for the spike — replace with a persistent backend
    (SQLite, Postgres, or Redis) before any production use.
    See backlog item 3.P.1 "Persistent job store".

Replacement contract:
    Any persistent implementation must satisfy BaseJobStore below.
    The job orchestrator and API routes depend only on this interface,
    so swapping the backend requires only changing the injection point
    in app/main.py.
"""

from abc import ABC, abstractmethod
from app.models.experience import Experience


class BaseJobStore(ABC):
    @abstractmethod
    async def save(self, experience: Experience) -> None:
        """Persist or update an experience. Called after every status transition."""
        ...

    @abstractmethod
    async def get(self, job_id: str) -> Experience | None:
        """Return experience by ID, or None if not found."""
        ...

    @abstractmethod
    async def list_ids(self) -> list[str]:
        """Return all known job IDs. Order is not guaranteed."""
        ...

    @abstractmethod
    async def delete(self, job_id: str) -> bool:
        """Remove a job by ID. Returns True if something was deleted."""
        ...


class InMemoryJobStore(BaseJobStore):
    """
    Non-persistent, single-process job store.

    Limitations:
    - Jobs are lost on restart.
    - No concurrency safety beyond Python's GIL.
    - No audit trail, no resumability, no TTL/eviction.
    """

    def __init__(self) -> None:
        self._store: dict[str, Experience] = {}

    async def save(self, experience: Experience) -> None:
        self._store[experience.id] = experience

    async def get(self, job_id: str) -> Experience | None:
        return self._store.get(job_id)

    async def list_ids(self) -> list[str]:
        return list(self._store.keys())

    async def delete(self, job_id: str) -> bool:
        return self._store.pop(job_id, None) is not None
