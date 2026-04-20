import math
from app.core.config import settings
from app.core.logging import get_logger
from app.models.intent import ExperienceMode, PromptIntent
from app.models.media import FallbackLevel, MediaCandidate
from app.models.place import PlaceCandidate, ScoreBreakdown

logger = get_logger(__name__)

# OSM tag → scenic value bonus
_SCENIC_TAG_SCORES: dict[tuple[str, str | None], float] = {
    ("natural", "peak"): 0.8,
    ("natural", "cliff"): 0.7,
    ("natural", "waterfall"): 0.6,
    ("tourism", "viewpoint"): 0.5,
    ("natural", "valley"): 0.5,
    ("historic", "ruins"): 0.4,
    ("natural", "heath"): 0.4,
    ("natural", "fell"): 0.4,
    ("natural", "bare_rock"): 0.5,
    ("natural", "glacier"): 0.7,
    ("natural", "saddle"): 0.6,
    ("place", "isolated_dwelling"): 0.3,
}

_ABANDONED_INDUSTRIAL_BONUS_TAGS = {
    ("landuse", "industrial"),
    ("ruins", "industrial"),
    ("man_made", "works"),
}

# Themes → OSM tag patterns that earn prompt_relevance score
_THEME_TAG_PATTERNS: dict[str, list[tuple[str, str | None]]] = {
    "abandoned_industrial": [
        ("ruins", "industrial"), ("disused:man_made", None),
        ("landuse", "industrial"), ("historic", "ruins"),
    ],
    "mountain_pass": [
        ("mountain_pass", "yes"), ("natural", "saddle"), ("natural", "peak"),
    ],
    "isolation": [
        ("place", "isolated_dwelling"), ("natural", "fell"), ("natural", "heath"),
    ],
    "panoramic_view": [
        ("tourism", "viewpoint"), ("natural", "cliff"), ("natural", "peak"),
    ],
    "ruins": [
        ("historic", "ruins"), ("ruins", None),
    ],
    "wilderness": [
        ("natural", "bare_rock"), ("natural", "glacier"), ("natural", "fell"),
    ],
    "scenic_road": [
        ("tourism", "viewpoint"), ("natural", "valley"),
    ],
    "industrial_heritage": [
        ("historic", "ruins"), ("man_made", "works"),
    ],
    "remote_nature": [
        ("natural", "fell"), ("natural", "heath"), ("natural", "bare_rock"),
    ],
}


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _prompt_relevance(place: PlaceCandidate, intent: PromptIntent) -> float:
    tags = place.tags
    matched = 0

    for theme in intent.themes:
        patterns = _THEME_TAG_PATTERNS.get(theme, [])
        for tag_key, tag_val in patterns:
            if tag_key in tags and (tag_val is None or tags[tag_key] == tag_val):
                matched += 1
                break

    if not intent.themes:
        return 0.1

    base = matched / len(intent.themes)

    # Bonus for abandoned + disused combination
    if intent.mode == ExperienceMode.ABANDONED_INDUSTRIAL:
        if "abandoned" in tags.get("disused", "") or tags.get("abandoned") == "yes":
            base = min(1.0, base + 0.1)

    return max(0.1, base)


def _media_availability(media: MediaCandidate | None, fallback: FallbackLevel) -> float:
    if media is None:
        return 0.0
    if fallback == FallbackLevel.FULL:
        return 0.7 * media.coverage_score + 0.3
    if fallback == FallbackLevel.PARTIAL_MEDIA:
        return 0.3 * media.confidence + 0.15
    return 0.0


def _scenic_value(place: PlaceCandidate) -> float:
    score = 0.0
    tags = place.tags

    for (key, val), bonus in _SCENIC_TAG_SCORES.items():
        if key in tags and (val is None or tags[key] == val):
            score = max(score, bonus)

    # Abandoned industrial bonus
    if (
        ("landuse", tags.get("landuse")) in _ABANDONED_INDUSTRIAL_BONUS_TAGS
        and tags.get("abandoned") == "yes"
    ):
        score = max(score, 0.6)

    return min(1.0, score)


def _diversity_bonus(
    place: PlaceCandidate,
    already_selected: list[PlaceCandidate],
) -> float:
    if not already_selected:
        return 1.0

    min_km = settings.pipeline_min_diversity_km
    max_km = settings.pipeline_max_diversity_km

    avg_dist = sum(
        _haversine_km(place.lat, place.lon, sel.lat, sel.lon)
        for sel in already_selected
    ) / len(already_selected)

    if avg_dist < min_km:
        return 0.0
    if avg_dist > max_km:
        return 0.5
    return (avg_dist - min_km) / (max_km - min_km)


def score_place(
    place: PlaceCandidate,
    intent: PromptIntent,
    media: MediaCandidate | None,
    fallback: FallbackLevel,
    already_selected: list[PlaceCandidate],
) -> PlaceCandidate:
    w = settings.scoring

    pr = _prompt_relevance(place, intent)
    ma = _media_availability(media, fallback)
    sv = _scenic_value(place)
    db = _diversity_bonus(place, already_selected)
    rc = 0.5  # route_coherence is neutral in first iteration

    final = (
        w.prompt_relevance * pr
        + w.media_availability * ma
        + w.scenic_value * sv
        + w.diversity_bonus * db
        + w.route_coherence * rc
    )

    place.prompt_relevance_score = pr
    place.scenic_score = sv
    place.final_score = round(final, 4)
    place.score_breakdown = ScoreBreakdown(
        prompt_relevance=round(pr, 4),
        media_availability=round(ma, 4),
        scenic_value=round(sv, 4),
        diversity_bonus=round(db, 4),
        route_coherence=round(rc, 4),
    )

    return place
