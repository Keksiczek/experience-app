"""Scoring engine V2.

Scoring components:
  prompt_relevance    — how well OSM tags match intent themes
  media_availability  — quality / availability of imagery
  scenic_value        — intrinsic landscape / atmospheric value of the place
  diversity_bonus     — spatial diversity vs already-selected stops
  route_coherence     — placeholder (neutral 0.5 until routing implemented)
  context_richness    — richness of OSM metadata (meaningful tags count)
  similarity_penalty  — deduction for tag-profile similarity to already-selected places
  combo_bonus         — bonus when relevance + media + context are all strong

Penalties and bonuses are applied to the weighted sum, clamped to [0, 1].
Decision reasons are attached to ScoreBreakdown for per-place debugging.
"""

import math
from app.core.config import settings
from app.core.logging import get_logger
from app.models.intent import ExperienceMode, PromptIntent
from app.models.media import FallbackLevel, MediaCandidate
from app.models.place import PlaceCandidate, ScoreBreakdown

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Tag tables
# ---------------------------------------------------------------------------

_SCENIC_TAG_SCORES: dict[tuple[str, str | None], float] = {
    ("natural", "peak"): 0.85,
    ("natural", "cliff"): 0.75,
    ("natural", "glacier"): 0.80,
    ("natural", "waterfall"): 0.65,
    ("natural", "gorge"): 0.70,
    ("natural", "saddle"): 0.65,
    ("tourism", "viewpoint"): 0.60,
    ("natural", "valley"): 0.55,
    ("natural", "fell"): 0.45,
    ("natural", "heath"): 0.40,
    ("natural", "bare_rock"): 0.55,
    ("historic", "ruins"): 0.45,
    ("place", "isolated_dwelling"): 0.35,
    ("mountain_pass", "yes"): 0.80,
    ("natural", "moor"): 0.40,
    ("natural", "scree"): 0.45,
}

_THEME_TAG_PATTERNS: dict[str, list[tuple[str, str | None]]] = {
    "abandoned_industrial": [
        ("ruins", "industrial"), ("disused:man_made", None),
        ("landuse", "industrial"), ("historic", "ruins"),
        ("railway", "abandoned"), ("disused:railway", None),
        ("landuse", "brownfield"), ("historic", "mine"),
    ],
    "mountain_pass": [
        ("mountain_pass", "yes"), ("natural", "saddle"), ("natural", "peak"),
    ],
    "isolation": [
        ("place", "isolated_dwelling"), ("natural", "fell"), ("natural", "heath"),
        ("natural", "moor"), ("place", "locality"),
    ],
    "panoramic_view": [
        ("tourism", "viewpoint"), ("natural", "cliff"), ("natural", "peak"),
        ("natural", "gorge"),
    ],
    "ruins": [
        ("historic", "ruins"), ("ruins", None), ("ruins", "industrial"),
    ],
    "wilderness": [
        ("natural", "bare_rock"), ("natural", "glacier"), ("natural", "fell"),
        ("natural", "heath"), ("natural", "scree"),
    ],
    "scenic_road": [
        ("tourism", "viewpoint"), ("natural", "valley"), ("natural", "gorge"),
    ],
    "industrial_heritage": [
        ("historic", "ruins"), ("man_made", "works"), ("historic", "mine"),
        ("historic", "adit"), ("landuse", "brownfield"),
    ],
    "remote_nature": [
        ("natural", "fell"), ("natural", "heath"), ("natural", "bare_rock"),
        ("natural", "moor"), ("natural", "scree"),
    ],
}

# Tags that have meaningful informational content for narration
_MEANINGFUL_TAGS = {
    "natural", "historic", "tourism", "man_made", "ruins", "disused:man_made",
    "landuse", "mountain_pass", "place", "railway", "ele", "wikidata",
    "wikipedia", "description", "inscription", "operator", "heritage",
}

_ABANDONED_INDUSTRIAL_BONUS_TAGS = {
    ("landuse", "industrial"),
    ("ruins", "industrial"),
    ("man_made", "works"),
}


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ---------------------------------------------------------------------------
# Individual scoring components
# ---------------------------------------------------------------------------


def _prompt_relevance(place: PlaceCandidate, intent: PromptIntent) -> tuple[float, list[str]]:
    tags = place.tags
    matched = 0
    reasons: list[str] = []

    for theme in intent.themes:
        patterns = _THEME_TAG_PATTERNS.get(theme, [])
        for tag_key, tag_val in patterns:
            if tag_key in tags and (tag_val is None or tags[tag_key] == tag_val):
                matched += 1
                reasons.append(f"theme '{theme}' matched via tag {tag_key}={tags[tag_key]!r}")
                break

    if not intent.themes:
        return 0.1, ["no themes in intent"]

    base = matched / len(intent.themes)

    # Bonus for abandoned + disused combination (strong double signal)
    if intent.mode == ExperienceMode.ABANDONED_INDUSTRIAL:
        disused_val = tags.get("disused", "")
        abandoned_val = tags.get("abandoned", "")
        if "abandoned" in disused_val or abandoned_val == "yes":
            base = min(1.0, base + 0.15)
            reasons.append("bonus: abandoned+disused combination")

    # Signal-tier bonus — must_have places already passed the hard filter
    if place.signal_strength == "must_have":
        base = min(1.0, base + 0.1)
        reasons.append("signal_tier bonus: must_have")

    score = max(0.1, base)
    if not reasons:
        reasons.append(f"no themes matched ({len(intent.themes)} themes checked)")
    return score, reasons


def _media_availability(
    media: MediaCandidate | None, fallback: FallbackLevel
) -> tuple[float, list[str]]:
    reasons: list[str] = []
    if media is None:
        return 0.0, ["no media candidate"]
    if fallback == FallbackLevel.FULL:
        score = 0.7 * media.coverage_score + 0.3
        reasons.append(f"Mapillary FULL, coverage={media.coverage_score:.2f}")
        return score, reasons
    if fallback == FallbackLevel.PARTIAL_MEDIA:
        score = 0.3 * media.confidence + 0.15
        reasons.append(f"Wikimedia PARTIAL, confidence={media.confidence:.2f}")
        return score, reasons
    return 0.0, [f"fallback_level={fallback.value} — no usable media"]


def _scenic_value(place: PlaceCandidate) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []
    tags = place.tags

    for (key, val), bonus in _SCENIC_TAG_SCORES.items():
        if key in tags and (val is None or tags[key] == val):
            if bonus > score:
                score = bonus
                reasons = [f"scenic tag {key}={tags[key]!r} → {bonus:.2f}"]

    # Abandoned industrial bonus (derelict + industrial = atmosphere)
    if (
        ("landuse", tags.get("landuse")) in _ABANDONED_INDUSTRIAL_BONUS_TAGS
        and tags.get("abandoned") == "yes"
    ):
        new_score = max(score, 0.65)
        if new_score > score:
            score = new_score
            reasons.append("abandoned industrial combo → 0.65")

    if not reasons:
        reasons.append("no scenic tags found")

    return min(1.0, score), reasons


def _diversity_bonus(
    place: PlaceCandidate,
    already_selected: list[PlaceCandidate],
) -> tuple[float, list[str]]:
    if not already_selected:
        return 1.0, ["first stop — full diversity bonus"]

    min_km = settings.pipeline_min_diversity_km
    max_km = settings.pipeline_max_diversity_km

    avg_dist = sum(
        _haversine_km(place.lat, place.lon, sel.lat, sel.lon)
        for sel in already_selected
    ) / len(already_selected)

    if avg_dist < min_km:
        return 0.0, [f"too close to existing stops: avg {avg_dist:.1f} km < {min_km} km"]
    if avg_dist > max_km:
        return 0.5, [f"distant from existing stops: avg {avg_dist:.1f} km > {max_km} km → capped at 0.5"]

    score = (avg_dist - min_km) / (max_km - min_km)
    return score, [f"avg distance to selected stops: {avg_dist:.1f} km → {score:.2f}"]


def _context_richness(place: PlaceCandidate) -> tuple[float, list[str]]:
    """Ratio of meaningful tags present, normalised to 0–1 (cap at 8 tags = 1.0)."""
    meaningful = [k for k in place.tags if k in _MEANINGFUL_TAGS]
    cap = 8
    score = min(1.0, len(meaningful) / cap)
    return score, [f"{len(meaningful)} meaningful tags → {score:.2f}"]


def _tag_profile(place: PlaceCandidate) -> frozenset[tuple[str, str]]:
    """Reduced tag fingerprint for similarity comparison."""
    relevant_keys = _MEANINGFUL_TAGS
    return frozenset(
        (k, v) for k, v in place.tags.items()
        if k in relevant_keys
    )


def _similarity_penalty(
    place: PlaceCandidate,
    already_selected: list[PlaceCandidate],
) -> tuple[float, list[str]]:
    """Deduction for places whose tag profile closely matches an already-selected stop."""
    if not already_selected:
        return 0.0, []

    profile = _tag_profile(place)
    if not profile:
        return 0.0, ["no profile tags — similarity check skipped"]

    max_similarity = 0.0
    for sel in already_selected:
        sel_profile = _tag_profile(sel)
        if not sel_profile:
            continue
        intersection = len(profile & sel_profile)
        union = len(profile | sel_profile)
        if union > 0:
            sim = intersection / union
            max_similarity = max(max_similarity, sim)

    # Penalty only kicks in above 0.6 Jaccard similarity
    if max_similarity < 0.6:
        return 0.0, []
    penalty = (max_similarity - 0.6) / 0.4 * 0.2  # max penalty = 0.2
    return round(penalty, 4), [f"tag similarity={max_similarity:.2f} to selected stop → -{penalty:.2f}"]


def _combo_bonus(pr: float, ma: float, cr: float) -> tuple[float, list[str]]:
    """Bonus when relevance + media + context are all above 0.5."""
    if pr >= 0.5 and ma >= 0.3 and cr >= 0.375:
        bonus = 0.08
        return bonus, [f"combo bonus: pr={pr:.2f}+ma={ma:.2f}+cr={cr:.2f} all strong → +{bonus}"]
    return 0.0, []


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def score_place(
    place: PlaceCandidate,
    intent: PromptIntent,
    media: MediaCandidate | None,
    fallback: FallbackLevel,
    already_selected: list[PlaceCandidate],
) -> PlaceCandidate:
    w = settings.scoring

    pr, pr_reasons = _prompt_relevance(place, intent)
    ma, ma_reasons = _media_availability(media, fallback)
    sv, sv_reasons = _scenic_value(place)
    db, db_reasons = _diversity_bonus(place, already_selected)
    cr, cr_reasons = _context_richness(place)
    sp, sp_reasons = _similarity_penalty(place, already_selected)
    cb, cb_reasons = _combo_bonus(pr, ma, cr)
    rc = 0.5  # route_coherence is neutral until routing is implemented

    # Weighted base score
    base = (
        w.prompt_relevance * pr
        + w.media_availability * ma
        + w.scenic_value * sv
        + w.diversity_bonus * db
        + w.route_coherence * rc
    )

    # Apply context richness as a soft modifier (±10%)
    # Low context → slight downward pressure; high context → slight boost
    context_modifier = (cr - 0.5) * 0.10
    final = base + context_modifier - sp + cb
    final = max(0.0, min(1.0, round(final, 4)))

    decision_reasons = (
        pr_reasons + ma_reasons + sv_reasons + db_reasons
        + cr_reasons + sp_reasons + cb_reasons
    )

    place.prompt_relevance_score = pr
    place.scenic_score = sv
    place.context_score = cr
    place.final_score = final
    place.score_breakdown = ScoreBreakdown(
        prompt_relevance=round(pr, 4),
        media_availability=round(ma, 4),
        scenic_value=round(sv, 4),
        diversity_bonus=round(db, 4),
        route_coherence=round(rc, 4),
        context_richness=round(cr, 4),
        similarity_penalty=round(sp, 4),
        combo_bonus=round(cb, 4),
        decision_reasons=decision_reasons,
    )

    return place
