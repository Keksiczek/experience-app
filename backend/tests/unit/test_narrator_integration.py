"""Integration tests for narrator.py with and without OllamaNarratorProvider.

Tests verify that:
- narrate_stops works correctly with ollama=None (pure template path)
- narrate_stops correctly uses LLM result when Ollama returns high-confidence output
- narrate_stops falls back to template when LLM returns low confidence
"""

import json

import pytest

from app.cache.base import BaseCache
from app.models.experience import ExperienceStop
from app.models.intent import ExperienceMode, PromptIntent
from app.models.media import FallbackLevel
from app.models.place import PlaceCandidate
from app.pipeline.narrator import narrate_stops
from app.providers.ollama_narrator import OllamaNarratorProvider


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

class _NullCache(BaseCache):
    async def get(self, key: str):
        return None

    async def set(self, key: str, value, ttl: int) -> None:
        pass

    async def delete(self, key: str) -> None:
        pass

    async def clear_expired(self) -> int:
        return 0


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _stop(place_id: str, fallback: FallbackLevel = FallbackLevel.NO_MEDIA) -> ExperienceStop:
    return ExperienceStop(
        id="s1", order=1, place_id=place_id,
        lat=50.0, lon=18.0, name="Důl Anna",
        short_title="Důl Anna", why_here="", narration="",
        fallback_level=fallback,
    )


def _place(place_id: str) -> PlaceCandidate:
    return PlaceCandidate(
        id=place_id, lat=50.0, lon=18.0, name="Důl Anna",
        source_type="osm",
        tags={"ruins": "industrial", "historic": "mine", "landuse": "industrial"},
    )


def _intent() -> PromptIntent:
    return PromptIntent(
        original_prompt="opuštěné průmyslové oblasti v Polsku",
        mode=ExperienceMode.ABANDONED_INDUSTRIAL,
        confidence=0.9,
    )


def _ollama_response(inner: dict) -> dict:
    return {"response": json.dumps(inner), "done": True}


# ---------------------------------------------------------------------------
# Test 1: ollama=None → pure template narrator, no import error
# ---------------------------------------------------------------------------

async def test_no_ollama_uses_template_narrator():
    """narrate_stops with ollama=None runs clean template path for all stops."""
    stops = [_stop("p1", FallbackLevel.NO_MEDIA)]
    place_map = {"p1": _place("p1")}

    result = await narrate_stops(stops, place_map, _intent(), ollama=None)

    assert len(result) == 1
    assert result[0].used_llm_narration is False
    assert result[0].llm_fallback_reason is None
    assert result[0].why_here != ""      # template narrator produced something
    assert result[0].narration != ""
    assert 0.0 <= result[0].narration_confidence <= 1.0


# ---------------------------------------------------------------------------
# Test 2: full LLM flow → stop has used_llm_narration=True and non-empty narration
# ---------------------------------------------------------------------------

async def test_llm_narration_applied_when_high_confidence(httpx_mock):
    """Ollama returns confidence 0.85 → ExperienceStop.used_llm_narration=True."""
    httpx_mock.add_response(
        json=_ollama_response({
            "why_here": "Historický uhelný důl odpovídá promptu.",
            "narration": "Důl Anna byl provozován od roku 1880. Dnes leží v troskách.",
            "confidence": 0.85,
            "sources_used": ["osm_tags", "place_name"],
        })
    )

    provider = OllamaNarratorProvider(
        cache=_NullCache(),
        base_url="http://localhost:11434",
        model="phi3.5",
    )

    stops = [_stop("p1", FallbackLevel.PARTIAL_MEDIA)]
    place_map = {"p1": _place("p1")}

    result = await narrate_stops(stops, place_map, _intent(), ollama=provider)

    assert result[0].used_llm_narration is True
    assert result[0].narration_confidence == pytest.approx(0.85)
    assert "Historický" in result[0].why_here
    assert "troskách" in result[0].narration
    assert "osm_tags" in result[0].grounding_sources
    assert result[0].llm_fallback_reason is None


# ---------------------------------------------------------------------------
# Test 3: LLM returns low confidence → template fallback applied
# ---------------------------------------------------------------------------

async def test_template_fallback_on_low_llm_confidence(httpx_mock):
    """Ollama confidence 0.2 → template narrator takes over, stop.used_llm_narration=False."""
    httpx_mock.add_response(
        json=_ollama_response({
            "why_here": "Neznámá lokalita.",
            "narration": "Málo dat.",
            "confidence": 0.2,
            "sources_used": [],
        })
    )

    provider = OllamaNarratorProvider(
        cache=_NullCache(),
        base_url="http://localhost:11434",
        model="phi3.5",
    )

    stops = [_stop("p1", FallbackLevel.NO_MEDIA)]
    place_map = {"p1": _place("p1")}

    result = await narrate_stops(stops, place_map, _intent(), ollama=provider)

    assert result[0].used_llm_narration is False
    assert result[0].llm_fallback_reason == "low_confidence"
    # Template narrator should have filled in why_here
    assert result[0].why_here != ""


# ---------------------------------------------------------------------------
# Test 4: multiple stops — LLM applied per stop independently
# ---------------------------------------------------------------------------

async def test_multiple_stops_each_gets_narration(httpx_mock):
    """Two stops → Ollama called twice (once per stop), each gets its own result."""
    httpx_mock.add_response(
        json=_ollama_response({
            "why_here": "Zastávka 1 odpovídá promptu.",
            "narration": "Popis zastávky 1.",
            "confidence": 0.9,
            "sources_used": ["osm_tags"],
        })
    )
    httpx_mock.add_response(
        json=_ollama_response({
            "why_here": "Zastávka 2 odpovídá promptu.",
            "narration": "Popis zastávky 2.",
            "confidence": 0.8,
            "sources_used": ["osm_tags"],
        })
    )

    provider = OllamaNarratorProvider(
        cache=_NullCache(),
        base_url="http://localhost:11434",
        model="phi3.5",
    )

    stops = [
        _stop("p1", FallbackLevel.FULL),
        ExperienceStop(
            id="s2", order=2, place_id="p2",
            lat=50.1, lon=18.1, name="Továrna Prokop",
            short_title="Továrna Prokop", why_here="", narration="",
            fallback_level=FallbackLevel.NO_MEDIA,
        ),
    ]
    place_map = {
        "p1": _place("p1"),
        "p2": PlaceCandidate(
            id="p2", lat=50.1, lon=18.1, name="Továrna Prokop",
            source_type="osm",
            tags={"ruins": "industrial", "man_made": "works"},
        ),
    }

    result = await narrate_stops(stops, place_map, _intent(), ollama=provider)

    assert all(s.used_llm_narration for s in result)
    assert result[0].why_here != result[1].why_here


# ---------------------------------------------------------------------------
# Test 5: Ollama connection error for all stops → template fallback for all
# ---------------------------------------------------------------------------

async def test_ollama_down_falls_back_for_all_stops(httpx_mock):
    """Connection error → all stops get template narration, none raises."""
    import httpx as _httpx
    httpx_mock.add_exception(_httpx.ConnectError("refused"))
    httpx_mock.add_exception(_httpx.ConnectError("refused"))

    provider = OllamaNarratorProvider(
        cache=_NullCache(),
        base_url="http://localhost:11434",
        model="phi3.5",
    )

    stops = [_stop("p1"), _stop("p2")]
    place_map = {"p1": _place("p1"), "p2": _place("p2")}

    result = await narrate_stops(stops, place_map, _intent(), ollama=provider)

    assert all(not s.used_llm_narration for s in result)
    assert all("ollama_error" in (s.llm_fallback_reason or "") for s in result)
    # Template narrator filled in content
    assert all(s.why_here != "" for s in result)
