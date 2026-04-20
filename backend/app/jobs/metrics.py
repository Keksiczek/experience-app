"""
Computes whole-experience quality metrics after the composer step.
All inputs are structured data from previous pipeline steps — nothing is invented.
"""

import math
from app.core.config import settings
from app.models.experience import ExperienceQualityMetrics, ExperienceStop
from app.models.media import FallbackLevel
from app.models.place import PlaceCandidate


def compute_quality_metrics(
    stops: list[ExperienceStop],
    place_map: dict[str, PlaceCandidate],
) -> ExperienceQualityMetrics:
    if not stops:
        return ExperienceQualityMetrics()

    imagery_coverage_ratio = _imagery_coverage(stops)
    fallback_distribution = _fallback_distribution(stops)
    diversity_score = _diversity_score(stops)
    route_coherence_score = _route_coherence(stops)
    narration_confidence = _avg_narration_confidence(stops)
    context_richness = _context_richness(stops, place_map)

    return ExperienceQualityMetrics(
        imagery_coverage_ratio=round(imagery_coverage_ratio, 3),
        fallback_distribution=fallback_distribution,
        diversity_score=round(diversity_score, 3),
        route_coherence_score=round(route_coherence_score, 3),
        narration_confidence=round(narration_confidence, 3),
        context_richness=round(context_richness, 3),
    )


def _imagery_coverage(stops: list[ExperienceStop]) -> float:
    with_media = sum(
        1 for s in stops
        if s.fallback_level not in (FallbackLevel.NO_MEDIA, FallbackLevel.MINIMAL)
    )
    return with_media / len(stops)


def _fallback_distribution(stops: list[ExperienceStop]) -> dict[str, int]:
    dist: dict[str, int] = {}
    for stop in stops:
        key = stop.fallback_level.value
        dist[key] = dist.get(key, 0) + 1
    return dist


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _diversity_score(stops: list[ExperienceStop]) -> float:
    """Average pairwise distance / max_diversity_km, clamped to [0, 1]."""
    if len(stops) < 2:
        return 0.0

    pairs = [
        _haversine_km(a.lat, a.lon, b.lat, b.lon)
        for i, a in enumerate(stops)
        for b in stops[i + 1:]
    ]
    avg_km = sum(pairs) / len(pairs)
    return min(1.0, avg_km / settings.pipeline_max_diversity_km)


def _route_coherence(stops: list[ExperienceStop]) -> float:
    """
    Heuristic: ratio of consecutive stop distances that are <= 2× the median.
    High coherence = stops progress geographically, no large random jumps.
    Returns 0.5 for experiences with fewer than 3 stops (insufficient data).
    """
    if len(stops) < 3:
        return 0.5

    dists = [
        _haversine_km(stops[i].lat, stops[i].lon, stops[i + 1].lat, stops[i + 1].lon)
        for i in range(len(stops) - 1)
    ]
    median = sorted(dists)[len(dists) // 2]
    coherent = sum(1 for d in dists if d <= median * 2.0)
    return coherent / len(dists)


def _avg_narration_confidence(stops: list[ExperienceStop]) -> float:
    if not stops:
        return 0.0
    return sum(s.narration_confidence for s in stops) / len(stops)


def _context_richness(
    stops: list[ExperienceStop],
    place_map: dict[str, PlaceCandidate],
) -> float:
    """Average meaningful tag count per stop, normalised (cap at 8 = 1.0)."""
    TAG_CAP = 8
    skip = {"source", "name", "name:en", "name:cs"}

    counts = []
    for stop in stops:
        place = place_map.get(stop.place_id)
        if not place:
            counts.append(0)
            continue
        meaningful = sum(
            1 for k, v in place.tags.items()
            if k not in skip and v not in ("yes", "no", "")
        )
        counts.append(min(meaningful, TAG_CAP))

    return sum(counts) / (len(counts) * TAG_CAP) if counts else 0.0
