"""Experience Composer: greedy stop selection with diversity-aware rescoring,
followed by geographic ordering via _order_stops.

Each selected stop carries decision_reasons and (where applicable) fallback_reason
so poor outputs can be traced back to their root cause.
"""

import math
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
    stops = _order_stops(stops, intent.route_style)
    logger.info(
        "composer_done",
        stops=len(stops),
        threshold_used=threshold,
        route_style=intent.route_style,
    )
    return stops


def _order_stops(
    stops: list[ExperienceStop],
    route_style: str,
) -> list[ExperienceStop]:
    """Re-order stops for geographic coherence based on route_style.

    linear   — sort along the axis of greatest spread (W→E or S→N)
    loop     — nearest-neighbor starting from westernmost point
    scattered — preserve original greedy-selection order
    """
    if len(stops) <= 1:
        for i, s in enumerate(stops):
            s.stop_order = i
        return stops

    if route_style == "linear":
        lats = [s.lat for s in stops]
        lons = [s.lon for s in stops]
        lat_spread = max(lats) - min(lats)
        lon_spread = max(lons) - min(lons)
        if lon_spread > lat_spread:
            ordered = sorted(stops, key=lambda s: s.lon)   # west → east
        else:
            ordered = sorted(stops, key=lambda s: s.lat)   # south → north

    elif route_style == "loop":
        ordered = _nearest_neighbor_loop(stops)

    else:  # "scattered" or unknown
        ordered = list(stops)

    for i, stop in enumerate(ordered):
        stop.stop_order = i

    return ordered


def _nearest_neighbor_loop(stops: list[ExperienceStop]) -> list[ExperienceStop]:
    """Nearest-neighbor Hamiltonian path starting from the westernmost stop.
    Pure stdlib math — no numpy.
    """
    def _dist2(a: ExperienceStop, b: ExperienceStop) -> float:
        dlat = a.lat - b.lat
        dlon = a.lon - b.lon
        return dlat * dlat + dlon * dlon

    remaining = sorted(stops, key=lambda s: s.lon)  # westernmost first
    ordered: list[ExperienceStop] = [remaining.pop(0)]

    while remaining:
        current = ordered[-1]
        nearest = min(remaining, key=lambda s: _dist2(current, s))
        ordered.append(nearest)
        remaining.remove(nearest)

    return ordered


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
                "weak OSM signal — place matched only low-priority tags"
            )
        if place.discovery_warnings:
            decision_reasons.extend(
                f"discovery warning: {w}" for w in place.discovery_warnings
            )

        stops.append(
            ExperienceStop(
                id=str(uuid.uuid4()),
                order=order,
                stop_order=order - 1,   # will be overwritten by _order_stops
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
