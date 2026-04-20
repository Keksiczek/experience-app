import asyncio
import hashlib
import json
import time
from abc import ABC, abstractmethod
from typing import Any

import httpx

from app.cache.base import BaseCache
from app.core.logging import get_logger

logger = get_logger(__name__)


class ProviderError(Exception):
    def __init__(self, provider: str, reason: str, status_code: int | None = None) -> None:
        self.provider = provider
        self.reason = reason
        self.status_code = status_code
        super().__init__(f"[{provider}] {reason}")


class BaseProvider(ABC):
    def __init__(self, cache: BaseCache) -> None:
        self._cache = cache
        self._client: httpx.AsyncClient | None = None

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @property
    @abstractmethod
    def ttl_seconds(self) -> int:
        ...

    @abstractmethod
    def cache_key(self, params: dict[str, Any]) -> str:
        ...

    @abstractmethod
    async def _fetch_live(self, params: dict[str, Any]) -> Any:
        """Perform the actual HTTP request. Raise ProviderError on failure."""
        ...

    async def fetch(self, params: dict[str, Any]) -> Any:
        key = self.cache_key(params)
        cached = await self._cache.get(key)

        if cached is not None:
            logger.debug("cache_hit", provider=self.name, key=key)
            return cached

        start = time.monotonic()
        result = await self._fetch_live(params)
        elapsed_ms = int((time.monotonic() - start) * 1000)

        await self._cache.set(key, result, self.ttl_seconds)

        logger.info(
            "provider_fetch",
            provider=self.name,
            duration_ms=elapsed_ms,
            result_count=len(result) if isinstance(result, list) else 1,
        )
        return result

    def _make_cache_key(self, prefix: str, params: dict[str, Any]) -> str:
        payload = json.dumps(params, sort_keys=True)
        digest = hashlib.sha256(payload.encode()).hexdigest()[:16]
        return f"{prefix}:{digest}"

    async def _http_get(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
        retries: int = 3,
    ) -> dict[str, Any]:
        """GET with exponential backoff retry. Raises ProviderError on final failure."""
        delays = [2, 4, 8]
        last_error: Exception | None = None

        async with httpx.AsyncClient(timeout=timeout) as client:
            for attempt in range(retries):
                try:
                    response = await client.get(url, params=params, headers=headers)

                    if response.status_code == 429:
                        wait = delays[min(attempt, len(delays) - 1)]
                        logger.warning(
                            "rate_limited",
                            provider=self.name,
                            attempt=attempt + 1,
                            retry_in_s=wait,
                        )
                        await asyncio.sleep(wait)
                        continue

                    response.raise_for_status()
                    return response.json()

                except httpx.HTTPStatusError as e:
                    raise ProviderError(self.name, f"HTTP {e.response.status_code}", e.response.status_code) from e
                except httpx.TimeoutException as e:
                    last_error = e
                    if attempt < retries - 1:
                        await asyncio.sleep(delays[attempt])
                except httpx.RequestError as e:
                    last_error = e
                    if attempt < retries - 1:
                        await asyncio.sleep(delays[attempt])

        raise ProviderError(self.name, f"All {retries} attempts failed: {last_error}")
