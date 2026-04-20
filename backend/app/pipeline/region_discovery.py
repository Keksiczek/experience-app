import json
from pathlib import Path

from app.core.logging import get_logger
from app.models.intent import PromptIntent
from app.models.place import RegionCandidate
from app.providers.nominatim import NominatimProvider

logger = get_logger(__name__)

_STATIC_REGIONS_PATH = Path(__file__).parent.parent.parent.parent / "data" / "samples" / "regions.json"


async def discover_regions(
    intent: PromptIntent,
    nominatim: NominatimProvider,
) -> list[RegionCandidate]:
    candidates: list[RegionCandidate] = []

    # Try Nominatim for each preferred region
    for region_name in intent.preferred_regions:
        results = await nominatim.geocode_region(region_name)
        if results:
            candidates.extend(results[:1])  # Take best result per region name
            logger.info("region_found", source="nominatim", region=region_name)

    if candidates:
        return candidates

    # Fallback: static region map
    logger.warning("nominatim_no_results", preferred_regions=intent.preferred_regions)
    static = _load_static_regions(intent)
    if static:
        logger.info("region_found", source="static_fallback", count=len(static))
        return static

    logger.error(
        "region_discovery_failed",
        preferred_regions=intent.preferred_regions,
        mode=intent.mode,
    )
    return []


def _load_static_regions(intent: PromptIntent) -> list[RegionCandidate]:
    if not _STATIC_REGIONS_PATH.exists():
        return []

    try:
        with open(_STATIC_REGIONS_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []

    results = []
    search_terms = [r.lower() for r in intent.preferred_regions] + [intent.mode.value]

    for region in data.get("regions", []):
        name = region.get("name", "").lower()
        aliases = [a.lower() for a in region.get("aliases", [])]
        if any(term in name or term in aliases for term in search_terms):
            results.append(
                RegionCandidate(
                    name=region["name"],
                    lat_min=region["bbox"][0],
                    lon_min=region["bbox"][1],
                    lat_max=region["bbox"][2],
                    lon_max=region["bbox"][3],
                    source="static_fallback",
                    confidence=0.5,
                )
            )

    return results[:2]
