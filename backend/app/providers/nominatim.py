import asyncio
import time
from typing import Any

from app.cache.base import BaseCache
from app.core.config import settings
from app.core.logging import get_logger
from app.models.place import RegionCandidate
from app.providers.base import BaseProvider, ProviderError

logger = get_logger(__name__)

_LAST_REQUEST_TIME: float = 0.0
_RATE_LIMIT_INTERVAL = 1.1  # seconds, Nominatim requires 1 req/s


class NominatimProvider(BaseProvider):
    BASE_URL = "https://nominatim.openstreetmap.org/search"
    USER_AGENT = "experience-app/0.1 (geo-exploration; contact@example.com)"

    def __init__(self, cache: BaseCache) -> None:
        super().__init__(cache)

    @property
    def name(self) -> str:
        return "nominatim"

    @property
    def ttl_seconds(self) -> int:
        return settings.cache_ttl_nominatim

    def cache_key(self, params: dict[str, Any]) -> str:
        return self._make_cache_key("nominatim", params)

    async def _fetch_live(self, params: dict[str, Any]) -> Any:
        global _LAST_REQUEST_TIME

        # Enforce 1 req/s rate limit
        elapsed = time.monotonic() - _LAST_REQUEST_TIME
        if elapsed < _RATE_LIMIT_INTERVAL:
            await asyncio.sleep(_RATE_LIMIT_INTERVAL - elapsed)
        _LAST_REQUEST_TIME = time.monotonic()

        query = params.get("q", "")
        result = await self._http_get(
            self.BASE_URL,
            params={"q": query, "format": "jsonv2", "limit": 5},
            headers={"User-Agent": self.USER_AGENT},
        )
        return result

    async def geocode_region(self, region_name: str) -> list[RegionCandidate]:
        """Convert region name to RegionCandidate list via Nominatim."""
        try:
            results = await self.fetch({"q": region_name})
        except ProviderError as e:
            logger.warning("nominatim_failed", region=region_name, reason=str(e))
            return []

        candidates = []
        for item in results:
            bbox = item.get("boundingbox")
            if not bbox or len(bbox) < 4:
                continue
            candidates.append(
                RegionCandidate(
                    name=item.get("display_name", region_name),
                    lat_min=float(bbox[0]),
                    lat_max=float(bbox[1]),
                    lon_min=float(bbox[2]),
                    lon_max=float(bbox[3]),
                    source="nominatim",
                    confidence=float(item.get("importance", 0.5)),
                )
            )
        return candidates
