from abc import ABC, abstractmethod
from typing import Any


class BaseCache(ABC):
    @abstractmethod
    async def get(self, key: str) -> Any | None:
        """Return cached value or None if missing/expired."""
        ...

    @abstractmethod
    async def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        """Store value with TTL. Overwrites existing key."""
        ...

    @abstractmethod
    async def delete(self, key: str) -> None:
        ...

    @abstractmethod
    async def clear_expired(self) -> int:
        """Remove all expired entries. Returns count of removed entries."""
        ...
