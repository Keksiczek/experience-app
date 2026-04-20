"""Experience Composer: greedy stop selection with diversity-aware rescoring.

Each selected stop carries decision_reasons and (where applicable) fallback_reason
so poor outputs can be traced back to their root cause.
"""

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
    threshold_lowered = False
    selected: list[PlaceCandidate] = []
    remaining = list(places)

    while len(selected) < intent.estimated_stops and remaining:
        # Rescore all remaining candidates given current selection
        for place in remaining:
            media, fallback = media_map.get(place.id, (None, FallbackLevel.NO_MEDIA))
            score_place(place, intent, media, fallback, selected)

        remaining.sort(key=lambda p: p.final_score, reverse=True)
        best = remaining[0]

        if best.final_score < threshold:
            if not threshold_lowered:
                threshold = settings.pipeline_score_threshold_emergency
                threshold_lowered = True
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

    stops = _build_stops(selected, media_map, threshold_lowered)
    logger.info("composer_done", stops=len(stops), threshold_used=threshold)
    return stops


def _build_stops(
    places: list[PlaceCandidate],
    media_map: dict[str, tuple[MediaCandidate | None, FallbackLevel]],
    used_emergency_threshold: bool,
) -> list[ExperienceStop]:
    stops = []
    for order, place in enumerate(places, start=1):
        media, fallback = media_map.get(place.id, (None, FallbackLevel.NO_MEDIA))

        # Assemble per-stop decision reasons from score breakdown
        bd = place.score_breakdown
        decision_reasons = list(bd.decision_reasons)
        decision_reasons.append(
            f"final_score={place.final_score:.3f} "
            f"(pr={bd.prompt_relevance:.2f}, ma={bd.media_availability:.2f}, "
            f"sv={bd.scenic_value:.2f}, db={bd.diversity_bonus:.2f}, "
            f"cr={bd.context_richness:.2f})"
        )
        if used_emergency_threshold:
            decision_reasons.append("selected via emergency threshold (score < normal threshold)")

        # Fallback reason
        fallback_reason: str | None = None
        if fallback == FallbackLevel.NO_MEDIA:
            fallback_reason = "Mapillary and Wikimedia both returned no results for this location"
        elif fallback == FallbackLevel.PARTIAL_MEDIA:
            fallback_reason = "Mapillary unavailable; using Wikimedia Commons photo"
        elif fallback == FallbackLevel.LOW_CONTEXT:
            fallback_reason = "Media found but metadata incomplete"
        elif fallback == FallbackLevel.MINIMAL:
            fallback_reason = "Only coordinate data available; no media or metadata"

        # Signal-strength note
        if place.signal_strength == "weak":
            decision_reasons.append(
                f"weak OSM signal — place matched only low-priority tags"
            )
        if place.discovery_warnings:
            decision_reasons.extend(
                f"discovery warning: {w}" for w in place.discovery_warnings
            )

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
                why_here="",
                narration="",
                fallback_level=fallback,
                score=place.final_score,
                decision_reasons=decision_reasons,
                fallback_reason=fallback_reason,
                emergency_threshold_used=used_emergency_threshold,
            )
        )
    return stops
