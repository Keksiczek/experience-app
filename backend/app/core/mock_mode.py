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
from app.providers.wikipedia import WikipediaProvider

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
    """Returns a deterministically rotated Mapillary-style response.

    The sample file has multiple distinct IDs; we pick one per place_id
    using a stable hash so subsequent calls for the same place return the
    same image, but different places see different shots — useful for
    demoing the click-out link in stop cards / theater hero.
    """

    def __init__(self, cache: BaseCache) -> None:
        super().__init__(cache)
        self._data: dict = _load_json("mapillary_sample.json")

    async def resolve_for_place(
        self, place_id: str, lat: float, lon: float
    ) -> tuple[MediaCandidate | None, FallbackLevel]:
        images = self._data.get("data", [])
        if not images:
            return None, FallbackLevel.NO_MEDIA

        idx = abs(hash(place_id)) % len(images)
        chosen = images[idx]
        thumb = chosen.get("thumb_256_url", "")
        if not thumb:
            return None, FallbackLevel.NO_MEDIA

        candidate = MediaCandidate(
            id=f"mapillary:{chosen.get('id', 'mock')}",
            place_id=place_id,
            provider=MediaProvider.MAPILLARY,
            media_type=MediaType.STREET_LEVEL,
            preview_url=thumb,
            viewer_ref=chosen.get("sequence", ""),
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


class MockWikipediaProvider(WikipediaProvider):
    """Returns a templated 'Wikipedia-like' summary for any stop.

    Real WikipediaProvider needs a Wikidata QID; mock places never go
    through the wikidata enrichment step, so we expose
    ``fetch_summary_for_stop`` which the enrichment pipeline picks up
    via duck typing.  Output language tracks the Czech UI.
    """

    _MODE_PREFIX = {
        "abandoned_industrial":
            "Tato bývalá průmyslová lokalita patří k charakteristickým "
            "stopám těžkého průmyslu v regionu. ",
        "remote_landscape":
            "Místo se nachází v relativně odlehlé části regionu, "
            "stranou hlavních dopravních koridorů. ",
        "scenic_roadtrip":
            "Lokalita patří mezi malebná místa vhodná k zastavení "
            "během průjezdu regionem. ",
    }

    # Three real Commons file titles for industrial-Silesia themed mocks.
    # Pretending we got these from a Wikipedia media-list lookup; rotated
    # by stop_order so different mocked stops show different galleries.
    _GALLERY_POOL = [
        [
            "Huta Pokój w Rudzie Śląskiej.jpg",
            "Walcownia w Hucie Pokój.jpg",
            "Pokoj steel mill chimney.jpg",
        ],
        [
            "Huta Florian Świętochłowice.jpg",
            "Huta Florian piec.jpg",
        ],
        [
            "Szyb Krystyna Bytom.jpg",
            "Bytom mining tower.jpg",
        ],
    ]

    async def fetch_summary_for_stop(  # type: ignore[override]
        self, stop, place
    ) -> dict[str, object] | None:
        name = stop.short_title or stop.name or ""
        if not name:
            return None
        tags = (place.tags if place is not None else None) or {}
        mode_hint = ""
        if tags.get("historic") in {"ruins", "industrial", "mine"} or tags.get("ruins"):
            mode_hint = self._MODE_PREFIX["abandoned_industrial"]
        elif tags.get("natural") in {"peak", "ridge", "valley"}:
            mode_hint = self._MODE_PREFIX["remote_landscape"]

        tag_descriptors = []
        if tags.get("historic"):
            tag_descriptors.append(f"klasifikace: {tags['historic']}")
        if tags.get("ruins"):
            tag_descriptors.append(f"typ ruin: {tags['ruins']}")
        if tags.get("landuse") == "industrial":
            tag_descriptors.append("průmyslové využití pozemku")
        if tags.get("man_made"):
            tag_descriptors.append(f"man_made: {tags['man_made']}")
        descriptor_sentence = (
            f"OpenStreetMap eviduje atributy: {'; '.join(tag_descriptors)}. "
            if tag_descriptors else ""
        )

        summary = (
            f"{name} — {mode_hint}{descriptor_sentence}"
            "Pro úplný kontext doporučujeme prozkoumat lokalitu na místě "
            "nebo si přečíst odpovídající článek na Wikipedii."
        )
        slug = name.replace(" ", "_")
        url = f"https://cs.wikipedia.org/wiki/{slug}"
        gallery = self._GALLERY_POOL[
            (stop.stop_order or 0) % len(self._GALLERY_POOL)
        ]
        return {"summary": summary, "url": url, "lang": "cs", "gallery": gallery}
