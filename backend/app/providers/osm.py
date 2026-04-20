"""Overpass / OSM provider with mode-specific signal tier presets.

Each mode defines four layers of OSM tag filters:
  must_have  → strongest, mode-defining signals
  strong     → good candidates — clearly relevant
  weak       → supplementary / contextual candidates
  blacklist  → tags that mark a place as noise for this mode

Query strategy:
  - must_have + strong + weak filters are combined into a single Overpass union.
  - After parsing, each element is tagged with the highest signal tier it matched.
  - Blacklisted elements are dropped entirely before returning.

Result limit (out center N) is per-query, not per-mode.  Tune via
settings.overpass_result_limit (default 80).
"""

from dataclasses import dataclass, field
from typing import Any

from app.cache.base import BaseCache
from app.core.config import settings
from app.core.logging import get_logger
from app.models.intent import ExperienceMode
from app.models.place import PlaceCandidate, RegionCandidate
from app.providers.base import BaseProvider, ProviderError

logger = get_logger(__name__)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# ---------------------------------------------------------------------------
# Noise / generic tags that we normalise away before name generation
# ---------------------------------------------------------------------------

_GENERIC_NAME_PREFIXES = ("OSM node", "OSM way", "OSM relation")


@dataclass
class ModePreset:
    """Tiered OSM filter preset for one experience mode."""
    must_have: list[str]    # Weight 1.0 in signal_strength
    strong: list[str]       # Weight 0.7
    weak: list[str]         # Weight 0.4
    blacklist: dict[str, list[str]] = field(default_factory=dict)   # tag → bad values


_PRESETS: dict[ExperienceMode, ModePreset] = {

    ExperienceMode.SCENIC_ROADTRIP: ModePreset(
        must_have=[
            '["natural"="peak"]["name"]',           # Named peaks only (unnamed clutter)
            '["natural"="saddle"]["name"]',
            '["mountain_pass"="yes"]',
            '["tourism"="viewpoint"]',
        ],
        strong=[
            '["natural"="cliff"]',
            '["natural"="valley"]["name"]',
            '["natural"="gorge"]',
            '["natural"="glacier"]',
            '["historic"="fort"]["natural"]',       # Fort with natural context
            '["route"="hiking"]["network"="iwn"]',  # International hiking routes (major)
        ],
        weak=[
            '["natural"="peak"]',                   # Unnamed peaks — low quality
            '["natural"="saddle"]',
            '["natural"="fell"]',
            '["place"="hamlet"]["is_in:mountain_range"]',
        ],
        blacklist={
            "amenity": ["restaurant", "cafe", "hotel", "parking", "fuel", "toilets"],
            "tourism": ["hotel", "motel", "hostel", "camp_site", "caravan_site"],
            "shop": [],   # any shop value
            "highway": ["motorway", "trunk", "primary"],  # busy roads without scenic context
        },
    ),

    ExperienceMode.REMOTE_LANDSCAPE: ModePreset(
        must_have=[
            '["natural"="fell"]',
            '["natural"="heath"]',
            '["natural"="bare_rock"]',
            '["natural"="glacier"]',
            '["place"="isolated_dwelling"]',
        ],
        strong=[
            '["natural"="moor"]',
            '["natural"="wetland"]["wetland"="bog"]',
            '["natural"="grassland"]["name"]',
            '["natural"="scree"]',
            '["natural"="sand"]',                   # Sand desert / dune fields
            '["natural"="peak"]["ele"]',             # Peaks with elevation (remote mountain indicator)
            '["landuse"="meadow"]["name"]',
        ],
        weak=[
            '["natural"="water"]["name"]',          # Lakes / tarns in remote areas
            '["place"="locality"]',                 # Named localities with no settlement
            '["natural"="wood"]["name"]',
            '["natural"="valley"]["name"]',
        ],
        blacklist={
            "amenity": ["restaurant", "cafe", "hotel", "parking", "fuel", "toilets", "bar"],
            "tourism": ["hotel", "motel", "hostel", "attraction", "museum"],
            "shop": [],
            "place": ["city", "town", "village", "suburb"],
            "landuse": ["residential", "commercial", "retail", "industrial"],
        },
    ),

    ExperienceMode.ABANDONED_INDUSTRIAL: ModePreset(
        must_have=[
            '["ruins"="industrial"]',
            '["disused:man_made"]',
            '["landuse"="industrial"]["abandoned"="yes"]',
            '["man_made"="works"]["disused"="yes"]',
            '["historic"="ruins"]["industrial"="yes"]',
            '["railway"="abandoned"]',
            '["disused:railway"]',
        ],
        strong=[
            '["historic"="ruins"]',
            '["man_made"="chimney"]["disused"="yes"]',
            '["man_made"="water_tower"]["disused"="yes"]',
            '["building"="industrial"]["ruins"="yes"]',
            '["landuse"="brownfield"]',
            '["historic"="mine"]',
            '["historic"="adit"]',
            '["man_made"="mineshaft"]["disused"="yes"]',
        ],
        weak=[
            '["building"="industrial"]["abandoned"="yes"]',
            '["landuse"="industrial"]',              # Active or ambiguous industrial
            '["man_made"="works"]',                 # Active works — needs filtering
            '["historic"="industrial"]',
            '["man_made"="storage_tank"]["disused"="yes"]',
        ],
        blacklist={
            "amenity": ["restaurant", "cafe", "school", "hospital", "pharmacy"],
            "tourism": ["hotel", "museum", "attraction", "viewpoint"],
            "shop": [],
            "office": [],
            "landuse": ["residential", "commercial", "retail", "recreation_ground"],
        },
    ),
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
        preset = _PRESETS.get(mode)
        if preset is None:
            return ""

        all_filters = preset.must_have + preset.strong + preset.weak
        node_queries = "\n  ".join(f"node{tag}({bbox});" for tag in all_filters)
        way_queries = "\n  ".join(f"way{tag}({bbox});" for tag in all_filters)
        result_limit = getattr(settings, "overpass_result_limit", 80)

        return f"""
[out:json][timeout:45];
(
  {node_queries}
  {way_queries}
);
out center {result_limit};
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

    def _is_blacklisted(self, tags: dict[str, str], mode: ExperienceMode) -> bool:
        preset = _PRESETS.get(mode)
        if preset is None:
            return False
        for tag_key, bad_values in preset.blacklist.items():
            if tag_key in tags:
                if not bad_values:
                    return True  # any value is bad
                if tags[tag_key] in bad_values:
                    return True
        return False

    def _classify_signal_strength(
        self, tags: dict[str, str], mode: ExperienceMode
    ) -> str:
        """Return 'must_have' | 'strong' | 'weak' based on tag matches."""
        preset = _PRESETS.get(mode)
        if preset is None:
            return "weak"

        def _tag_matches_filter(tags: dict[str, str], osm_filter: str) -> bool:
            # Parse simple ["key"="value"] or ["key"] patterns
            import re as _re
            pairs = _re.findall(r'"([^"]+)"(?:="([^"]*)")?', osm_filter)
            for key, val in pairs:
                if key not in tags:
                    return False
                if val and tags[key] != val:
                    return False
            return bool(pairs)

        for tier, filters in [
            ("must_have", preset.must_have),
            ("strong", preset.strong),
        ]:
            for f in filters:
                if _tag_matches_filter(tags, f):
                    return tier
        return "weak"

    def _normalise_name(self, tags: dict[str, str], osm_type: str, osm_id: int) -> str:
        """Produce the best available name from OSM tags."""
        for key in ("name", "name:en", "name:de", "official_name", "old_name"):
            val = tags.get(key, "").strip()
            if val:
                return val
        # Generate a descriptive fallback from most-informative tags
        for key in ("natural", "ruins", "man_made", "historic", "landuse", "building"):
            val = tags.get(key, "").strip()
            if val:
                return f"{val.replace('_', ' ').title()} ({osm_type} {osm_id})"
        return f"OSM {osm_type} {osm_id}"

    def _parse_element(
        self, element: dict[str, Any], mode: ExperienceMode
    ) -> PlaceCandidate | None:
        lat = element.get("lat") or element.get("center", {}).get("lat")
        lon = element.get("lon") or element.get("center", {}).get("lon")
        if lat is None or lon is None:
            return None

        osm_type = element.get("type", "node")
        osm_id = element.get("id", 0)
        tags: dict[str, str] = element.get("tags", {})

        if self._is_blacklisted(tags, mode):
            return None

        name = self._normalise_name(tags, osm_type, osm_id)
        signal_strength = self._classify_signal_strength(tags, mode)

        discovery_warnings: list[str] = []
        if not tags.get("name"):
            discovery_warnings.append("no_name_tag")
        if len(tags) < 2:
            discovery_warnings.append("sparse_tags")

        return PlaceCandidate(
            id=f"osm:{osm_type}:{osm_id}",
            lat=float(lat),
            lon=float(lon),
            name=name,
            source_type="osm",
            tags=tags,
            signal_strength=signal_strength,
            discovery_warnings=discovery_warnings,
        )

    async def discover_places(
        self, region: RegionCandidate, mode: ExperienceMode
    ) -> list[PlaceCandidate]:
        query = self._build_query(region, mode)
        if not query:
            logger.error("overpass_no_query", region=region.name, mode=mode)
            return []

        try:
            raw = await self.fetch({"query": query})
        except ProviderError as e:
            logger.error("overpass_failed", region=region.name, mode=mode, reason=str(e))
            return []

        elements = raw.get("elements", [])
        parsed = [self._parse_element(el, mode) for el in elements]
        valid = [p for p in parsed if p is not None]

        # Sort: must_have first, then strong, then weak
        tier_order = {"must_have": 0, "strong": 1, "weak": 2}
        valid.sort(key=lambda p: tier_order.get(p.signal_strength, 2))

        blacklisted = len(elements) - len(valid)
        logger.info(
            "overpass_results",
            region=region.name,
            mode=mode,
            raw_count=len(elements),
            valid_count=len(valid),
            blacklisted=blacklisted,
            must_have=sum(1 for p in valid if p.signal_strength == "must_have"),
            strong=sum(1 for p in valid if p.signal_strength == "strong"),
            weak=sum(1 for p in valid if p.signal_strength == "weak"),
        )
        return valid
