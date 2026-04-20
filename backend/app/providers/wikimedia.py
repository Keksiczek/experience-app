from typing import Any

from app.cache.base import BaseCache
from app.core.config import settings
from app.core.logging import get_logger
from app.models.media import FallbackLevel, MediaCandidate, MediaProvider, MediaType
from app.providers.base import BaseProvider, ProviderError

logger = get_logger(__name__)

WIKIMEDIA_API = "https://commons.wikimedia.org/w/api.php"


class WikimediaProvider(BaseProvider):
    USER_AGENT = "experience-app/0.1 (geo-exploration; contact@example.com)"

    def __init__(self, cache: BaseCache) -> None:
        super().__init__(cache)

    @property
    def name(self) -> str:
        return "wikimedia"

    @property
    def ttl_seconds(self) -> int:
        return settings.cache_ttl_wikimedia

    def cache_key(self, params: dict[str, Any]) -> str:
        return self._make_cache_key("wikimedia", params)

    async def _fetch_live(self, params: dict[str, Any]) -> Any:
        lat = params["lat"]
        lon = params["lon"]
        radius = params.get("radius", settings.pipeline_wikimedia_radius_m)

        return await self._http_get(
            WIKIMEDIA_API,
            params={
                "action": "query",
                "list": "geosearch",
                "gscoord": f"{lat}|{lon}",
                "gsradius": radius,
                "gslimit": 10,
                "gsnamespace": 6,
                "format": "json",
            },
            headers={"User-Agent": self.USER_AGENT},
        )

    async def resolve_for_place(
        self, place_id: str, lat: float, lon: float
    ) -> tuple[MediaCandidate | None, FallbackLevel]:
        try:
            raw = await self.fetch({"lat": lat, "lon": lon})
        except ProviderError as e:
            logger.warning("wikimedia_failed", place_id=place_id, reason=str(e))
            return None, FallbackLevel.NO_MEDIA

        items = raw.get("query", {}).get("geosearch", [])
        if not items:
            return None, FallbackLevel.NO_MEDIA

        first = items[0]
        title = first.get("title", "")
        dist = float(first.get("dist", 0))

        thumb_url = self._thumb_url(title)
        candidate = MediaCandidate(
            id=f"wikimedia:{title.replace(' ', '_')}",
            place_id=place_id,
            provider=MediaProvider.WIKIMEDIA,
            media_type=MediaType.PHOTO,
            preview_url=thumb_url,
            viewer_ref=title,
            coverage_score=0.5,
            confidence=max(0.1, 1.0 - dist / settings.pipeline_wikimedia_radius_m),
            distance_m=dist,
        )
        return candidate, FallbackLevel.PARTIAL_MEDIA

    @staticmethod
    def _thumb_url(title: str, width: int = 512) -> str:
        # Commons thumbnail URL pattern
        filename = title.removeprefix("File:").replace(" ", "_")
        return (
            f"https://commons.wikimedia.org/wiki/Special:FilePath/"
            f"{filename}?width={width}"
        )
