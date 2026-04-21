"""Place Discovery: wraps the Overpass provider and adds pipeline-level
quality gates, deduplication, and explicit discovery warnings.

After place discovery, Wikidata context is fetched concurrently for all
candidates (max 5 at a time) and stored on each PlaceCandidate.wikidata.
"""

import asyncio

from app.core.config import settings
from app.core.logging import get_logger
from app.models.intent import PromptIntent
from app.models.place import PlaceCandidate, RegionCandidate
from app.providers.osm import OverpassProvider
from app.providers.wikidata import WikidataProvider

logger = get_logger(__name__)

_WIKIDATA_CONCURRENCY = 5


class TooFewPlacesError(Exception):
    def __init__(self, found: int, minimum: int, warnings: list[str]) -> None:
        self.found = found
        self.minimum = minimum
        self.warnings = warnings
        super().__init__(f"Nedostatek míst: nalezeno {found}, minimum {minimum}")


async def discover_places(
    intent: PromptIntent,
    regions: list[RegionCandidate],
    overpass: OverpassProvider,
    wikidata: WikidataProvider | None = None,
) -> tuple[list[PlaceCandidate], list[str]]:
    """Return (places, discovery_warnings).

    Raises TooFewPlacesError if the hard minimum is not met.
    If wikidata provider is supplied, enriches all candidates concurrently
    (max _WIKIDATA_CONCURRENCY simultaneous requests).
    """
    all_places: list[PlaceCandidate] = []
    discovery_warnings: list[str] = []

    for region in regions:
        places = await overpass.discover_places(region, intent.mode)
        for place in places:
            place.region_id = region.name
        all_places.extend(places)

        # Per-region warnings
        if not places:
            discovery_warnings.append(
                f"region '{region.name}': Overpass returned zero results"
            )
        elif len(places) < 5:
            discovery_warnings.append(
                f"region '{region.name}': only {len(places)} raw results — "
                "try broader bbox or different tags"
            )

    # Deduplicate by OSM id
    seen: set[str] = set()
    unique: list[PlaceCandidate] = []
    for place in all_places:
        if place.id not in seen:
            seen.add(place.id)
            unique.append(place)

    # Signal-quality summary
    must_have = sum(1 for p in unique if p.signal_strength == "must_have")
    strong = sum(1 for p in unique if p.signal_strength == "strong")
    weak = sum(1 for p in unique if p.signal_strength == "weak")

    if must_have == 0:
        discovery_warnings.append(
            "no must-have signal places found — results may be low quality"
        )
    if weak > 0 and (must_have + strong) == 0:
        discovery_warnings.append(
            f"all {weak} candidates are weak-signal only — expect low scoring"
        )
    if len(unique) > 0:
        no_name_ratio = sum(
            1 for p in unique if "no_name_tag" in p.discovery_warnings
        ) / len(unique)
        if no_name_ratio > 0.5:
            discovery_warnings.append(
                f"{no_name_ratio:.0%} of candidates have no name tag — narration will be generic"
            )

    logger.info(
        "place_discovery_complete",
        total=len(unique),
        regions=len(regions),
        mode=intent.mode,
        must_have=must_have,
        strong=strong,
        weak=weak,
        warnings=discovery_warnings,
    )

    if len(unique) < settings.pipeline_min_places:
        raise TooFewPlacesError(len(unique), settings.pipeline_min_places, discovery_warnings)

    if len(unique) < settings.pipeline_ideal_places:
        discovery_warnings.append(
            f"suboptimal_place_count: found {len(unique)}, ideal is {settings.pipeline_ideal_places}"
        )
        logger.warning(
            "suboptimal_place_count",
            found=len(unique),
            ideal=settings.pipeline_ideal_places,
        )

    # Wikidata enrichment — concurrent, bounded by semaphore
    if wikidata is not None and unique:
        await _enrich_with_wikidata(unique, wikidata)
        wikidata_count = sum(1 for p in unique if p.wikidata is not None)
        logger.info(
            "wikidata_enrichment_complete",
            enriched=wikidata_count,
            total=len(unique),
        )

    return unique, discovery_warnings


async def _enrich_with_wikidata(
    places: list[PlaceCandidate],
    wikidata: WikidataProvider,
) -> None:
    sem = asyncio.Semaphore(_WIKIDATA_CONCURRENCY)

    async def enrich(place: PlaceCandidate) -> None:
        async with sem:
            ctx = await wikidata.fetch_context_for_place(
                place.id, place.lat, place.lon, place.name
            )
            if ctx is not None:
                place.wikidata = ctx

    await asyncio.gather(*[enrich(p) for p in places])
