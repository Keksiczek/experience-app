from typing import Any

from app.cache.base import BaseCache
from app.core.config import settings
from app.core.logging import get_logger
from app.models.media import FallbackLevel, MediaCandidate, MediaProvider, MediaType
from app.providers.base import BaseProvider, ProviderError

logger = get_logger(__name__)

MAPILLARY_BASE = "https://graph.mapillary.com/images"


def _sequence_count_to_score(count: int) -> float:
    if count == 0:
        return 0.0
    elif count <= 2:
        return 0.4
    elif count <= 9:
        return 0.7
    return 1.0


class MapillaryProvider(BaseProvider):
    def __init__(self, cache: BaseCache) -> None:
        super().__init__(cache)
        self._enabled = bool(settings.mapillary_api_key)

    @property
    def name(self) -> str:
        return "mapillary"

    @property
    def ttl_seconds(self) -> int:
        return settings.cache_ttl_mapillary

    def cache_key(self, params: dict[str, Any]) -> str:
        return self._make_cache_key("mapillary", params)

    async def _fetch_live(self, params: dict[str, Any]) -> Any:
        if not self._enabled:
            raise ProviderError(self.name, "API key not configured")

        lat = params["lat"]
        lon = params["lon"]
        radius = params.get("radius", settings.pipeline_mapillary_radius_m)

        return await self._http_get(
            MAPILLARY_BASE,
            params={
                "fields": "id,thumb_256_url,sequence,geometry",
                "bbox": f"{lon - 0.01},{lat - 0.01},{lon + 0.01},{lat + 0.01}",
                "limit": 20,
            },
            headers={"Authorization": f"OAuth {settings.mapillary_api_key}"},
        )

    async def resolve_for_place(
        self, place_id: str, lat: float, lon: float
    ) -> tuple[MediaCandidate | None, FallbackLevel]:
        if not self._enabled:
            logger.warning("mapillary_skipped", reason="no_api_key", place_id=place_id)
            return None, FallbackLevel.NO_MEDIA

        try:
            raw = await self.fetch({"lat": lat, "lon": lon})
        except ProviderError as e:
            logger.warning("mapillary_failed", place_id=place_id, reason=str(e))
            return None, FallbackLevel.NO_MEDIA

        images = raw.get("data", [])
        coverage_score = _sequence_count_to_score(len(images))

        if not images:
            return None, FallbackLevel.NO_MEDIA

        first = images[0]
        thumb = first.get("thumb_256_url", "")
        if not thumb:
            return None, FallbackLevel.NO_MEDIA

        candidate = MediaCandidate(
            id=f"mapillary:{first.get('id', 'unknown')}",
            place_id=place_id,
            provider=MediaProvider.MAPILLARY,
            media_type=MediaType.STREET_LEVEL,
            preview_url=thumb,
            viewer_ref=first.get("sequence", ""),
            coverage_score=coverage_score,
            confidence=coverage_score,
        )
        return candidate, FallbackLevel.FULL
