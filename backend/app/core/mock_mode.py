"""Mock providers for local development without live API calls.

Enable with MOCK_MODE=true in environment. Sample data is loaded from
data/samples/ at startup — no HTTP requests are ever made.

Usage:
    MOCK_MODE=true uvicorn app.main:app --reload
    curl -X POST /experiences -d '{"prompt": "opuštěné průmyslové oblasti v Horním Slezsku"}'
"""

import json
from pathlib import Path
from typing import Any

from app.cache.base import BaseCache
from app.models.intent import ExperienceMode
from app.models.media import FallbackLevel, MediaCandidate, MediaProvider, MediaType
from app.models.place import PlaceCandidate, RegionCandidate
from app.providers.mapillary import MapillaryProvider
from app.providers.nominatim import NominatimProvider
from app.providers.osm import OverpassProvider
from app.providers.wikimedia import WikimediaProvider

_SAMPLES_DIR = Path(__file__).parent.parent.parent.parent / "data" / "samples"

_SILESIA_MATCH_TERMS = {
    "horní slezsko", "horn slezsko", "silesia", "slezsko",
    "katowice", "upper silesia", "slask", "śląsk",
}


def _load_json(filename: str) -> Any:
    path = _SAMPLES_DIR / filename
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class MockNominatimProvider(NominatimProvider):
    """Returns Silesia region for Silesia-related queries; empty list otherwise."""

    def __init__(self, cache: BaseCache) -> None:
        super().__init__(cache)
        self._data: list[dict] = _load_json("nominatim_silesia.json")

    async def geocode_region(self, region_name: str) -> list[RegionCandidate]:
        lower = region_name.lower()
        if not any(term in lower for term in _SILESIA_MATCH_TERMS):
            return []

        candidates = []
        for item in self._data:
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
                    confidence=float(item.get("importance", 0.75)),
                )
            )
        return candidates


class MockOverpassProvider(OverpassProvider):
    """Returns sample abandoned-industrial places for ABANDONED_INDUSTRIAL mode; empty otherwise."""

    def __init__(self, cache: BaseCache) -> None:
        super().__init__(cache)
        self._abandoned_data: dict = _load_json("overpass_silesia_abandoned.json")

    async def discover_places(
        self, region: RegionCandidate, mode: ExperienceMode
    ) -> list[PlaceCandidate]:
        if mode != ExperienceMode.ABANDONED_INDUSTRIAL:
            return []

        elements = self._abandoned_data.get("elements", [])
        parsed = [self._parse_element(el, mode) for el in elements]
        valid = [p for p in parsed if p is not None]

        tier_order = {"must_have": 0, "strong": 1, "weak": 2}
        valid.sort(key=lambda p: tier_order.get(p.signal_strength, 2))
        return valid


class MockMapillaryProvider(MapillaryProvider):
    """Returns a static Mapillary-style response regardless of coordinates."""

    def __init__(self, cache: BaseCache) -> None:
        super().__init__(cache)
        self._data: dict = _load_json("mapillary_sample.json")

    async def resolve_for_place(
        self, place_id: str, lat: float, lon: float
    ) -> tuple[MediaCandidate | None, FallbackLevel]:
        images = self._data.get("data", [])
        if not images:
            return None, FallbackLevel.NO_MEDIA

        first = images[0]
        thumb = first.get("thumb_256_url", "")
        if not thumb:
            return None, FallbackLevel.NO_MEDIA

        candidate = MediaCandidate(
            id=f"mapillary:{first.get('id', 'mock')}",
            place_id=place_id,
            provider=MediaProvider.MAPILLARY,
            media_type=MediaType.STREET_LEVEL,
            preview_url=thumb,
            viewer_ref=first.get("sequence", ""),
            coverage_score=0.7,
            confidence=0.7,
        )
        return candidate, FallbackLevel.FULL


class MockWikimediaProvider(WikimediaProvider):
    """Returns a static Wikimedia geosearch response regardless of coordinates."""

    def __init__(self, cache: BaseCache) -> None:
        super().__init__(cache)
        self._data: dict = _load_json("wikimedia_sample.json")

    async def resolve_for_place(
        self, place_id: str, lat: float, lon: float
    ) -> tuple[MediaCandidate | None, FallbackLevel]:
        items = self._data.get("query", {}).get("geosearch", [])
        if not items:
            return None, FallbackLevel.NO_MEDIA

        first = items[0]
        title = first.get("title", "")
        dist = float(first.get("dist", 200))

        candidate = MediaCandidate(
            id=f"wikimedia:{title.replace(' ', '_')}",
            place_id=place_id,
            provider=MediaProvider.WIKIMEDIA,
            media_type=MediaType.PHOTO,
            preview_url=WikimediaProvider._thumb_url(title),
            viewer_ref=title,
            coverage_score=0.5,
            confidence=max(0.1, 1.0 - dist / 1000),
            distance_m=dist,
        )
        return candidate, FallbackLevel.PARTIAL_MEDIA
