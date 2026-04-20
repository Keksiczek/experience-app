"""Smoke fixture tests driven by tests/fixtures/smoke_cases.yaml.

Each fixture exercises the intent parser against a representative real-world
prompt and checks that:
  - The expected mode is returned (or ValueError is acceptable where noted).
  - Confidence is not below the floor defined in the fixture.
  - Required warnings are present.
  - Forbidden warnings are absent.
  - At least one expected region is captured (when specified).
  - At least one expected mood / terrain is captured (when specified).
"""

from pathlib import Path

import pytest
import yaml

from app.models.intent import ExperienceMode
from app.pipeline.intent_parser import parse_intent

_FIXTURES_PATH = Path(__file__).parent / "fixtures" / "smoke_cases.yaml"


def _load_cases() -> list[dict]:
    with open(_FIXTURES_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("smoke_cases", [])


_CASES = _load_cases()
_CASE_IDS = [c["id"] for c in _CASES]


@pytest.mark.parametrize("case", _CASES, ids=_CASE_IDS)
def test_smoke_fixture(case: dict) -> None:
    prompt: str = case["prompt"]
    case_id: str = case["id"]

    try:
        intent = parse_intent(prompt)
    except ValueError:
        # For edge cases where ValueError is acceptable, the fixture's
        # expected_mode still defines what we'd want — but raising is OK for vague prompts.
        if case.get("min_confidence", 1.0) == 0.0:
            pytest.skip(f"[{case_id}] ValueError raised — acceptable for vague prompt")
        else:
            raise

    expected_mode = ExperienceMode(case["expected_mode"])
    min_confidence = float(case.get("min_confidence", 0.0))
    required_warnings: list[str] = case.get("expected_warnings_subset", [])
    forbidden_warnings: list[str] = case.get("forbidden_warnings", [])
    expected_regions: list[str] = case.get("expected_regions_any", [])
    expected_moods: list[str] = case.get("expected_mood_any", [])
    expected_terrains: list[str] = case.get("expected_terrain_any", [])

    # Mode
    assert intent.mode == expected_mode, (
        f"[{case_id}] expected mode={expected_mode.value}, got mode={intent.mode.value}"
    )

    # Confidence floor (we don't enforce a ceiling — high confidence is fine)
    assert intent.confidence >= min_confidence, (
        f"[{case_id}] confidence={intent.confidence:.2f} < floor={min_confidence:.2f}; "
        f"reasons: {intent.confidence_reasons}"
    )

    # Required warnings present
    for w in required_warnings:
        assert w in intent.parse_warnings, (
            f"[{case_id}] expected warning '{w}' not found in {intent.parse_warnings}"
        )

    # Forbidden warnings absent
    for w in forbidden_warnings:
        assert w not in intent.parse_warnings, (
            f"[{case_id}] forbidden warning '{w}' found in {intent.parse_warnings}"
        )

    # Region extraction — stem-based substring match (handles declined forms).
    # The fixture uses stems ("norsk", "alp", "polsk") that match any declined form.
    if expected_regions:
        region_texts = [r.lower() for r in intent.preferred_regions]
        found = any(
            any(exp.lower() in rt for rt in region_texts)
            for exp in expected_regions
        )
        assert found, (
            f"[{case_id}] none of {expected_regions} (as stems) found in "
            f"{intent.preferred_regions}"
        )

    # Mood extraction
    if expected_moods:
        found_any_mood = any(m in intent.mood for m in expected_moods)
        assert found_any_mood, (
            f"[{case_id}] none of {expected_moods} found in intent.mood={intent.mood}"
        )

    # Terrain extraction
    if expected_terrains:
        found_any_terrain = any(t in intent.terrain for t in expected_terrains)
        assert found_any_terrain, (
            f"[{case_id}] none of {expected_terrains} found in intent.terrain={intent.terrain}"
        )
