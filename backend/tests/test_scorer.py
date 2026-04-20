"""Scorer V2 tests.

Covers:
- Prompt relevance (matching vs. unrelated tags)
- Scenic value per tag type
- Diversity bonus and cluster penalty
- Context richness component
- Similarity penalty for near-duplicate tag profiles
- Combo bonus
- Score breakdown fields populated
- Final score in [0, 1]
- decision_reasons populated
"""

import pytest
from app.models.intent import ExperienceMode, PromptIntent
from app.models.media import FallbackLevel, MediaCandidate
from app.models.place import PlaceCandidate
from app.scoring.scorer import score_place


def _make_intent(mode: ExperienceMode) -> PromptIntent:
    from app.pipeline.intent_parser import _mode_to_themes
    return PromptIntent(
        original_prompt="test",
        mode=mode,
        themes=_mode_to_themes(mode),
        confidence=0.9,
    )


def _make_place(tags: dict, lat: float = 50.0, lon: float = 19.0) -> PlaceCandidate:
    return PlaceCandidate(
        id="osm:node:1",
        lat=lat,
        lon=lon,
        name="Test Place",
        source_type="osm",
        tags=tags,
    )


# ── Prompt relevance ────────────────────────────────────────────────────────

def test_high_relevance_for_matching_tags():
    intent = _make_intent(ExperienceMode.ABANDONED_INDUSTRIAL)
    place = _make_place({"ruins": "industrial", "landuse": "industrial"})
    scored = score_place(place, intent, None, FallbackLevel.NO_MEDIA, [])
    assert scored.score_breakdown.prompt_relevance > 0.5


def test_low_relevance_for_unrelated_tags():
    intent = _make_intent(ExperienceMode.ABANDONED_INDUSTRIAL)
    place = _make_place({"amenity": "restaurant"})
    scored = score_place(place, intent, None, FallbackLevel.NO_MEDIA, [])
    assert scored.score_breakdown.prompt_relevance <= 0.15


def test_must_have_tier_bonus():
    intent = _make_intent(ExperienceMode.ABANDONED_INDUSTRIAL)
    place = _make_place({"ruins": "industrial", "landuse": "industrial"})
    place.signal_strength = "must_have"
    scored = score_place(place, intent, None, FallbackLevel.NO_MEDIA, [])
    assert scored.score_breakdown.prompt_relevance >= 0.5


# ── Scenic value ────────────────────────────────────────────────────────────

def test_scenic_value_peak():
    intent = _make_intent(ExperienceMode.SCENIC_ROADTRIP)
    place = _make_place({"natural": "peak", "name": "Velký vrch"})
    scored = score_place(place, intent, None, FallbackLevel.NO_MEDIA, [])
    assert scored.score_breakdown.scenic_value >= 0.80


def test_scenic_value_glacier():
    intent = _make_intent(ExperienceMode.REMOTE_LANDSCAPE)
    place = _make_place({"natural": "glacier"})
    scored = score_place(place, intent, None, FallbackLevel.NO_MEDIA, [])
    assert scored.score_breakdown.scenic_value >= 0.75


def test_scenic_value_unscenic():
    intent = _make_intent(ExperienceMode.REMOTE_LANDSCAPE)
    place = _make_place({"landuse": "industrial"})
    scored = score_place(place, intent, None, FallbackLevel.NO_MEDIA, [])
    assert scored.score_breakdown.scenic_value == 0.0


# ── Diversity bonus ─────────────────────────────────────────────────────────

def test_diversity_bonus_penalizes_clusters():
    intent = _make_intent(ExperienceMode.ABANDONED_INDUSTRIAL)
    place = _make_place({"ruins": "industrial"})
    nearby = PlaceCandidate(
        id="osm:node:2", lat=50.001, lon=19.001,
        name="Nearby", source_type="osm", tags={},
    )
    scored = score_place(place, intent, None, FallbackLevel.NO_MEDIA, [nearby])
    assert scored.score_breakdown.diversity_bonus == 0.0


def test_diversity_bonus_first_stop_full():
    intent = _make_intent(ExperienceMode.SCENIC_ROADTRIP)
    place = _make_place({"natural": "peak"})
    scored = score_place(place, intent, None, FallbackLevel.NO_MEDIA, [])
    assert scored.score_breakdown.diversity_bonus == 1.0


# ── Context richness ────────────────────────────────────────────────────────

def test_context_richness_many_tags():
    intent = _make_intent(ExperienceMode.ABANDONED_INDUSTRIAL)
    place = _make_place({
        "ruins": "industrial",
        "historic": "ruins",
        "man_made": "works",
        "landuse": "industrial",
        "tourism": "attraction",
        "wikidata": "Q123",
        "heritage": "2",
        "name": "Old Steelworks",
    })
    scored = score_place(place, intent, None, FallbackLevel.NO_MEDIA, [])
    assert scored.score_breakdown.context_richness >= 0.7


def test_context_richness_sparse_tags():
    intent = _make_intent(ExperienceMode.SCENIC_ROADTRIP)
    place = _make_place({"natural": "peak"})
    scored = score_place(place, intent, None, FallbackLevel.NO_MEDIA, [])
    assert scored.score_breakdown.context_richness <= 0.25


# ── Similarity penalty ──────────────────────────────────────────────────────

def test_similarity_penalty_near_duplicate():
    intent = _make_intent(ExperienceMode.ABANDONED_INDUSTRIAL)
    tags = {
        "ruins": "industrial", "historic": "ruins", "man_made": "works",
        "landuse": "industrial",
    }
    place = _make_place(tags, lat=50.0, lon=19.0)
    # Already-selected stop with identical tags (different coords)
    selected = PlaceCandidate(
        id="osm:node:99", lat=50.5, lon=19.5,
        name="Twin", source_type="osm", tags=dict(tags),
    )
    scored = score_place(place, intent, None, FallbackLevel.NO_MEDIA, [selected])
    assert scored.score_breakdown.similarity_penalty > 0.0


def test_similarity_penalty_unrelated_tags():
    intent = _make_intent(ExperienceMode.SCENIC_ROADTRIP)
    place = _make_place({"natural": "peak"}, lat=50.0, lon=19.0)
    selected = PlaceCandidate(
        id="osm:node:99", lat=50.5, lon=19.5,
        name="Ruin", source_type="osm", tags={"ruins": "industrial", "landuse": "industrial"},
    )
    scored = score_place(place, intent, None, FallbackLevel.NO_MEDIA, [selected])
    assert scored.score_breakdown.similarity_penalty == 0.0


# ── Combo bonus ─────────────────────────────────────────────────────────────

def test_combo_bonus_high_all_three():
    """High relevance + full media + rich context → combo bonus."""
    intent = _make_intent(ExperienceMode.ABANDONED_INDUSTRIAL)
    place = _make_place({
        "ruins": "industrial", "historic": "ruins", "man_made": "works",
        "landuse": "industrial", "wikidata": "Q123", "heritage": "2",
    })
    media = MediaCandidate(
        id="m1", place_id="osm:node:1",
        provider="mapillary", media_type="street_level",
        preview_url="https://example.com/img.jpg",
        coverage_score=0.9, confidence=0.9,
    )
    scored = score_place(place, intent, media, FallbackLevel.FULL, [])
    assert scored.score_breakdown.combo_bonus > 0.0


# ── Score breakdown populated ───────────────────────────────────────────────

def test_score_breakdown_decision_reasons():
    intent = _make_intent(ExperienceMode.SCENIC_ROADTRIP)
    place = _make_place({"natural": "peak", "tourism": "viewpoint"})
    scored = score_place(place, intent, None, FallbackLevel.NO_MEDIA, [])
    assert len(scored.score_breakdown.decision_reasons) > 0


# ── Final score range ───────────────────────────────────────────────────────

def test_final_score_range():
    intent = _make_intent(ExperienceMode.REMOTE_LANDSCAPE)
    place = _make_place({"natural": "fell"})
    scored = score_place(place, intent, None, FallbackLevel.NO_MEDIA, [])
    assert 0.0 <= scored.final_score <= 1.0


def test_final_score_full_media_raises_score():
    intent = _make_intent(ExperienceMode.SCENIC_ROADTRIP)
    place = _make_place({"natural": "peak", "tourism": "viewpoint"})
    media = MediaCandidate(
        id="m1", place_id="osm:node:1",
        provider="mapillary", media_type="street_level",
        preview_url="https://example.com/img.jpg",
        coverage_score=0.8, confidence=0.9,
    )
    no_media_scored = score_place(
        _make_place({"natural": "peak"}), intent, None, FallbackLevel.NO_MEDIA, []
    )
    full_media_scored = score_place(place, intent, media, FallbackLevel.FULL, [])
    assert full_media_scored.final_score > no_media_scored.final_score
