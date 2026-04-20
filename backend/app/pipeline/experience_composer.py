import uuid
from app.core.config import settings
from app.core.logging import get_logger
from app.models.experience import ExperienceStop
from app.models.intent import PromptIntent
from app.models.media import FallbackLevel, MediaCandidate
from app.models.place import PlaceCandidate
from app.scoring.scorer import score_place

logger = get_logger(__name__)


def compose_experience(
    intent: PromptIntent,
    places: list[PlaceCandidate],
    media_map: dict[str, tuple[MediaCandidate | None, FallbackLevel]],
) -> list[ExperienceStop]:
    threshold = settings.pipeline_score_threshold
    selected: list[PlaceCandidate] = []

    # Greedy selection with diversity-aware scoring
    remaining = list(places)

    while len(selected) < intent.estimated_stops and remaining:
        # Score all remaining candidates given current selection
        for place in remaining:
            media, fallback = media_map.get(place.id, (None, FallbackLevel.NO_MEDIA))
            score_place(place, intent, media, fallback, selected)

        remaining.sort(key=lambda p: p.final_score, reverse=True)
        best = remaining[0]

        if best.final_score < threshold:
            if threshold == settings.pipeline_score_threshold:
                # Emergency threshold
                threshold = settings.pipeline_score_threshold_emergency
                logger.warning(
                    "score_threshold_lowered",
                    new_threshold=threshold,
                    best_score=best.final_score,
                )
                continue
            else:
                logger.info(
                    "no_more_qualifying_places",
                    selected=len(selected),
                    threshold=threshold,
                )
                break

        selected.append(best)
        remaining.remove(best)

    if not selected:
        logger.error("composer_no_stops_selected", places_evaluated=len(places))
        return []

    stops = _build_stops(selected, media_map)
    logger.info("composer_done", stops=len(stops), threshold_used=threshold)
    return stops


def _build_stops(
    places: list[PlaceCandidate],
    media_map: dict[str, tuple[MediaCandidate | None, FallbackLevel]],
) -> list[ExperienceStop]:
    stops = []
    for order, place in enumerate(places, start=1):
        media, fallback = media_map.get(place.id, (None, FallbackLevel.NO_MEDIA))
        stops.append(
            ExperienceStop(
                id=str(uuid.uuid4()),
                order=order,
                place_id=place.id,
                media_id=media.id if media else None,
                lat=place.lat,
                lon=place.lon,
                name=place.name,
                short_title=place.name,
                why_here="",        # filled by narrator
                narration="",       # filled by narrator
                fallback_level=fallback,
                score=place.final_score,
            )
        )
    return stops
