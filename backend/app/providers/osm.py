from typing import Any

from app.cache.base import BaseCache
from app.core.config import settings
from app.core.logging import get_logger
from app.models.intent import ExperienceMode
from app.models.place import PlaceCandidate, RegionCandidate
from app.providers.base import BaseProvider, ProviderError

logger = get_logger(__name__)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# OSM tag filters per experience mode
MODE_TAG_FILTERS: dict[ExperienceMode, list[str]] = {
    ExperienceMode.ABANDONED_INDUSTRIAL: [
        '["ruins"="industrial"]',
        '["disused:man_made"]',
        '["historic"="ruins"]["building"="industrial"]',
        '["landuse"="industrial"]["abandoned"="yes"]',
        '["man_made"="works"]["disused"="yes"]',
    ],
    ExperienceMode.SCENIC_ROADTRIP: [
        '["natural"="peak"]',
        '["natural"="cliff"]',
        '["natural"="valley"]',
        '["tourism"="viewpoint"]',
        '["natural"="saddle"]',
    ],
    ExperienceMode.REMOTE_LANDSCAPE: [
        '["natural"="bare_rock"]',
        '["natural"="heath"]',
        '["natural"="fell"]',
        '["place"="isolated_dwelling"]',
        '["natural"="glacier"]',
    ],
}


class OverpassProvider(BaseProvider):
    def __init__(self, cache: BaseCache) -> None:
        super().__init__(cache)

    @property
    def name(self) -> str:
        return "overpass"

    @property
    def ttl_seconds(self) -> int:
        return settings.cache_ttl_overpass

    def cache_key(self, params: dict[str, Any]) -> str:
        return self._make_cache_key("overpass", params)

    def _build_query(self, region: RegionCandidate, mode: ExperienceMode) -> str:
        bbox = f"{region.lat_min},{region.lon_min},{region.lat_max},{region.lon_max}"
        tag_filters = MODE_TAG_FILTERS.get(mode, [])

        node_queries = "\n  ".join(
            f"node{tag}({bbox});" for tag in tag_filters
        )
        way_queries = "\n  ".join(
            f"way{tag}({bbox});" for tag in tag_filters
        )

        return f"""
[out:json][timeout:45];
(
  {node_queries}
  {way_queries}
);
out center 50;
"""

    async def _fetch_live(self, params: dict[str, Any]) -> Any:
        query = params.get("query", "")
        try:
            result = await self._http_get(
                OVERPASS_URL,
                params={"data": query},
                timeout=60.0,
            )
        except Exception as e:
            raise ProviderError(self.name, f"Overpass query failed: {e}") from e
        return result

    def _parse_element(self, element: dict[str, Any]) -> PlaceCandidate | None:
        lat = element.get("lat") or element.get("center", {}).get("lat")
        lon = element.get("lon") or element.get("center", {}).get("lon")
        if lat is None or lon is None:
            return None

        osm_type = element.get("type", "node")
        osm_id = element.get("id", 0)
        tags = element.get("tags", {})
        name = tags.get("name") or tags.get("name:en") or f"OSM {osm_type} {osm_id}"

        return PlaceCandidate(
            id=f"osm:{osm_type}:{osm_id}",
            lat=float(lat),
            lon=float(lon),
            name=name,
            source_type="osm",
            tags=tags,
        )

    async def discover_places(
        self, region: RegionCandidate, mode: ExperienceMode
    ) -> list[PlaceCandidate]:
        query = self._build_query(region, mode)
        try:
            raw = await self.fetch({"query": query})
        except ProviderError as e:
            logger.error("overpass_failed", region=region.name, mode=mode, reason=str(e))
            return []

        elements = raw.get("elements", [])
        places = [self._parse_element(el) for el in elements]
        valid = [p for p in places if p is not None]

        logger.info(
            "overpass_results",
            region=region.name,
            mode=mode,
            raw_count=len(elements),
            valid_count=len(valid),
        )
        return valid
