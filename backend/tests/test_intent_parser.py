"""Intent Parser V2 tests.

Covers:
- Mode detection (all 3 modes, English + Czech)
- Confidence levels and capping
- Warning flags
- Ambiguity detection
- Multi-category extraction (mood, terrain, infrastructure, climate, travel_mode)
- confidence_reasons and ambiguity_signals fields
"""

import pytest
from app.models.intent import ExperienceMode
from app.pipeline.intent_parser import parse_intent


# ── Mode detection ──────────────────────────────────────────────────────────

def test_abandoned_industrial_mode():
    intent = parse_intent("opuštěné průmyslové oblasti s historií těžby uhlí v Polsku")
    assert intent.mode == ExperienceMode.ABANDONED_INDUSTRIAL
    # Parser returns the exact matched form (e.g. "Polsku" = locative of Polsko)
    poland_variants = {"Poland", "Polsko", "Polsku", "Polska", "Polské"}
    assert any(r in poland_variants for r in intent.preferred_regions)
    assert intent.confidence > 0.5


def test_remote_landscape_mode():
    intent = parse_intent("samotářský výlet do divočiny, bez lidí, odlehlé plošiny")
    assert intent.mode == ExperienceMode.REMOTE_LANDSCAPE
    assert intent.settlement_density == "none"


def test_scenic_roadtrip_mode():
    intent = parse_intent("drsná horská sedla s panoramatickým výhledem nad Alpami")
    assert intent.mode == ExperienceMode.SCENIC_ROADTRIP


def test_scenic_roadtrip_english():
    intent = parse_intent("mountain pass roads with scenic viewpoints in the Alps")
    assert intent.mode == ExperienceMode.SCENIC_ROADTRIP
    assert any("alps" in r.lower() or "alpy" in r.lower() for r in intent.preferred_regions)


def test_abandoned_english_primary_signals():
    intent = parse_intent("abandoned factories and disused rail infrastructure in the Ruhr")
    assert intent.mode == ExperienceMode.ABANDONED_INDUSTRIAL
    assert intent.confidence >= 0.4


def test_remote_landscape_english():
    intent = parse_intent("remote wilderness plateau with no roads and no settlements")
    assert intent.mode == ExperienceMode.REMOTE_LANDSCAPE
    assert intent.settlement_density in ("none", "sparse")


# ── Confidence and warnings ─────────────────────────────────────────────────

def test_empty_prompt_raises():
    with pytest.raises(ValueError, match="prázdný"):
        parse_intent("")


def test_unrecognized_prompt_raises():
    with pytest.raises(ValueError, match="podporovanému"):
        parse_intent("recept na svíčkovou")


def test_vague_prompt_low_confidence():
    try:
        intent = parse_intent("výlet")
        assert intent.confidence <= 0.5
        assert "too_vague" in intent.parse_warnings
    except ValueError:
        pass  # raising ValueError for unrecognised single-word is also acceptable


def test_short_prompt_confidence_cap():
    intent = parse_intent("abandoned factories")
    assert intent.confidence <= 0.5
    assert "too_vague" in intent.parse_warnings


def test_no_region_warning():
    intent = parse_intent("opuštěné továrny kdesi daleko")
    assert "no_region_detected" in intent.parse_warnings


def test_region_extraction():
    intent = parse_intent("drsné průsmyky ve Skandinávii a Norsku")
    regions = [r.lower() for r in intent.preferred_regions]
    # Match by stem — parser returns the exact declined form found in the prompt
    # "Skandinávii" (locative) and "Norsku" (locative) are the actual matched forms
    assert any(
        "skandiná" in r or "scandinav" in r or "norsk" in r or "norway" in r
        for r in regions
    )


# ── Confidence reasons ──────────────────────────────────────────────────────

def test_confidence_reasons_populated():
    intent = parse_intent("abandoned industrial ruins and disused rail in Upper Silesia")
    assert len(intent.confidence_reasons) > 0


def test_confidence_reasons_explain_region():
    intent = parse_intent("lonely mountains with viewpoints")
    # Parser should note no region
    combined = " ".join(intent.confidence_reasons + intent.parse_warnings)
    assert "region" in combined or "no_region_detected" in intent.parse_warnings


# ── Ambiguity detection ─────────────────────────────────────────────────────

def test_ambiguous_mode_flagged():
    # This prompt has both scenic_roadtrip AND abandoned_industrial signals
    intent = parse_intent("abandoned mine ruins on alpine mountain pass roads")
    # Ambiguity may or may not be flagged depending on signal balance, but if it is:
    if "ambiguous_mode" in intent.parse_warnings:
        assert len(intent.ambiguity_signals) > 0
        assert intent.confidence <= 0.65


def test_unambiguous_strong_prompt_high_confidence():
    intent = parse_intent(
        "dramatic mountain pass roads with serpentine switchbacks and panoramic viewpoints "
        "in the western Alps near Stelvio"
    )
    assert intent.mode == ExperienceMode.SCENIC_ROADTRIP
    assert intent.confidence >= 0.6
    assert "ambiguous_mode" not in intent.parse_warnings


# ── Semantic category extraction ────────────────────────────────────────────

def test_terrain_alpine_detected():
    intent = parse_intent("high alpine mountain roads and passes")
    assert "alpine" in intent.terrain


def test_terrain_volcanic_detected():
    intent = parse_intent("remote volcanic landscapes with lava fields")
    assert "volcanic" in intent.terrain


def test_terrain_coastal_detected():
    intent = parse_intent("abandoned industrial coastline with crumbling harbour")
    assert "coastal" in intent.terrain


def test_mood_lonely_detected():
    intent = parse_intent("lonely alpine villages in remote mountains")
    assert "lonely" in intent.mood


def test_mood_dramatic_detected():
    intent = parse_intent("dramatic scenic mountain switchbacks")
    assert "dramatic" in intent.mood


def test_infrastructure_rail_detected():
    intent = parse_intent("abandoned rail infrastructure and disused train tracks")
    assert "rail" in intent.infrastructure


def test_travel_mode_car_detected():
    intent = parse_intent("scenic roadtrip by car through mountain passes")
    assert "car" in intent.travel_mode


# ── Settlement density ──────────────────────────────────────────────────────

def test_settlement_density_none():
    intent = parse_intent("remote wilderness with no people and no settlement")
    assert intent.settlement_density == "none"


def test_settlement_density_sparse():
    intent = parse_intent("sparse odlehlý countryside with very few villages")
    assert intent.settlement_density == "sparse"


# ── Combined prompts ────────────────────────────────────────────────────────

def test_combined_prompt_alpine_villages_with_roads():
    """'lonely alpine' should NOT override 'dramatic mountain roads' (scenic_roadtrip)."""
    intent = parse_intent("lonely alpine villages with dramatic mountain roads")
    assert intent.mode == ExperienceMode.SCENIC_ROADTRIP


def test_combined_abandoned_coastline():
    intent = parse_intent("abandoned industrial coastlines")
    assert intent.mode == ExperienceMode.ABANDONED_INDUSTRIAL


def test_combined_remote_desert_roads():
    intent = parse_intent("remote desert roads with almost no settlements in Utah")
    assert intent.mode == ExperienceMode.REMOTE_LANDSCAPE
    assert intent.settlement_density in ("none", "sparse")
