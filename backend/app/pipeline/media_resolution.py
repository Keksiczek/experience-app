from app.core.logging import get_logger
from app.models.media import FallbackLevel, MediaCandidate
from app.models.place import PlaceCandidate
from app.providers.mapillary import MapillaryProvider
from app.providers.wikimedia import WikimediaProvider

logger = get_logger(__name__)


async def resolve_media(
    places: list[PlaceCandidate],
    mapillary: MapillaryProvider,
    wikimedia: WikimediaProvider,
) -> dict[str, tuple[MediaCandidate | None, FallbackLevel]]:
    """
    For each place: try Mapillary → fallback Wikimedia → NO_MEDIA.
    Returns dict keyed by place_id.
    """
    results: dict[str, tuple[MediaCandidate | None, FallbackLevel]] = {}

    for place in places:
        media, level = await mapillary.resolve_for_place(place.id, place.lat, place.lon)

        if media is None:
            media, level = await wikimedia.resolve_for_place(place.id, place.lat, place.lon)
            if media is None:
                level = FallbackLevel.NO_MEDIA

        logger.debug(
            "media_resolved",
            place_id=place.id,
            provider=media.provider if media else None,
            fallback_level=level,
        )
        results[place.id] = (media, level)

    no_media_count = sum(1 for _, (m, _) in results.items() if m is None)
    logger.info(
        "media_resolution_complete",
        total=len(places),
        no_media=no_media_count,
        coverage_pct=round((1 - no_media_count / max(len(places), 1)) * 100),
    )
    return results
