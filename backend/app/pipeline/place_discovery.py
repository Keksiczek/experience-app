from app.core.config import settings
from app.core.logging import get_logger
from app.models.intent import PromptIntent
from app.models.place import PlaceCandidate, RegionCandidate
from app.providers.osm import OverpassProvider

logger = get_logger(__name__)


class TooFewPlacesError(Exception):
    def __init__(self, found: int, minimum: int) -> None:
        self.found = found
        self.minimum = minimum
        super().__init__(f"Nedostatek míst: nalezeno {found}, minimum {minimum}")


async def discover_places(
    intent: PromptIntent,
    regions: list[RegionCandidate],
    overpass: OverpassProvider,
) -> list[PlaceCandidate]:
    all_places: list[PlaceCandidate] = []

    for region in regions:
        places = await overpass.discover_places(region, intent.mode)
        for place in places:
            place.region_id = region.name
        all_places.extend(places)

    # Deduplicate by id
    seen: set[str] = set()
    unique = []
    for place in all_places:
        if place.id not in seen:
            seen.add(place.id)
            unique.append(place)

    logger.info(
        "place_discovery_complete",
        total=len(unique),
        regions=len(regions),
        mode=intent.mode,
    )

    if len(unique) < settings.pipeline_min_places:
        raise TooFewPlacesError(len(unique), settings.pipeline_min_places)

    if len(unique) < settings.pipeline_ideal_places:
        logger.warning(
            "suboptimal_place_count",
            found=len(unique),
            ideal=settings.pipeline_ideal_places,
        )

    return unique
