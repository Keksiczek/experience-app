import pytest
from app.models.intent import ExperienceMode, PromptIntent
from app.models.media import FallbackLevel
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


def _make_place(tags: dict) -> PlaceCandidate:
    return PlaceCandidate(
        id="osm:node:1",
        lat=50.0,
        lon=19.0,
        name="Test Place",
        source_type="osm",
        tags=tags,
    )


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


def test_scenic_value_peak():
    intent = _make_intent(ExperienceMode.SCENIC_ROADTRIP)
    place = _make_place({"natural": "peak", "name": "Velký vrch"})
    scored = score_place(place, intent, None, FallbackLevel.NO_MEDIA, [])
    assert scored.score_breakdown.scenic_value >= 0.8


def test_diversity_bonus_penalizes_clusters():
    intent = _make_intent(ExperienceMode.ABANDONED_INDUSTRIAL)
    place = _make_place({"ruins": "industrial"})
    nearby = PlaceCandidate(
        id="osm:node:2", lat=50.001, lon=19.001,
        name="Nearby", source_type="osm", tags={},
    )
    scored = score_place(place, intent, None, FallbackLevel.NO_MEDIA, [nearby])
    assert scored.score_breakdown.diversity_bonus == 0.0


def test_final_score_range():
    intent = _make_intent(ExperienceMode.REMOTE_LANDSCAPE)
    place = _make_place({"natural": "fell"})
    scored = score_place(place, intent, None, FallbackLevel.NO_MEDIA, [])
    assert 0.0 <= scored.final_score <= 1.0
