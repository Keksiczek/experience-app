import pytest
from app.models.intent import ExperienceMode
from app.pipeline.intent_parser import parse_intent


def test_abandoned_industrial_mode():
    intent = parse_intent("opuštěné průmyslové oblasti s historií těžby uhlí v Polsku")
    assert intent.mode == ExperienceMode.ABANDONED_INDUSTRIAL
    assert "Poland" in intent.preferred_regions or "Polsko" in intent.preferred_regions
    assert intent.confidence > 0.5


def test_remote_landscape_mode():
    intent = parse_intent("samotářský roadtrip po divočině, žádní turisté")
    assert intent.mode == ExperienceMode.REMOTE_LANDSCAPE
    assert intent.settlement_density == "none"


def test_scenic_roadtrip_mode():
    intent = parse_intent("drsná horská sedla s panoramatickým výhledem")
    assert intent.mode == ExperienceMode.SCENIC_ROADTRIP


def test_empty_prompt_raises():
    with pytest.raises(ValueError, match="prázdný"):
        parse_intent("")


def test_unrecognized_prompt_raises():
    with pytest.raises(ValueError, match="nepodporovanému"):
        parse_intent("recept na svíčkovou")


def test_vague_prompt_low_confidence():
    intent = parse_intent("výlet")
    assert intent.confidence <= 0.4
    assert "too_vague" in intent.parse_warnings


def test_no_region_warning():
    intent = parse_intent("opuštěné továrny kdesi daleko")
    assert "no_region_detected" in intent.parse_warnings


def test_region_extraction():
    intent = parse_intent("drsné průsmyky ve Skandinávii a Norsku")
    regions = [r.lower() for r in intent.preferred_regions]
    assert any("skandinávie" in r or "scandinavia" in r or "norsko" in r or "norway" in r for r in regions)
