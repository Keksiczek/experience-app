"""Unit tests for OllamaNarratorProvider.

Uses pytest-httpx to mock HTTP without live network calls.
Each test creates a fresh provider with a null or dict cache.
"""

import json

import pytest

from app.cache.base import BaseCache
from app.models.experience import ExperienceStop, NarrationResult
from app.models.intent import ExperienceMode, PromptIntent
from app.models.media import FallbackLevel
from app.models.place import PlaceCandidate
from app.providers.ollama_narrator import OllamaNarratorProvider


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

class _NullCache(BaseCache):
    """Cache that never hits — forces live fetch every time."""
    async def get(self, key: str):
        return None

    async def set(self, key: str, value, ttl: int) -> None:
        pass

    async def delete(self, key: str) -> None:
        pass

    async def clear_expired(self) -> int:
        return 0


class _DictCache(BaseCache):
    """In-memory cache that actually stores values — for testing cache hits."""
    def __init__(self) -> None:
        self._store: dict = {}

    async def get(self, key: str):
        return self._store.get(key)

    async def set(self, key: str, value, ttl: int) -> None:
        self._store[key] = value

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)

    async def clear_expired(self) -> int:
        return 0


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _make_provider(cache: BaseCache | None = None) -> OllamaNarratorProvider:
    return OllamaNarratorProvider(
        cache=cache or _NullCache(),
        base_url="http://localhost:11434",
        model="phi3.5",
    )


def _make_stop(place_id: str = "osm:node:1") -> ExperienceStop:
    return ExperienceStop(
        id="s1", order=1, place_id=place_id,
        lat=50.0, lon=18.0, name="Důl Anna",
        short_title="Důl Anna", why_here="", narration="",
        fallback_level=FallbackLevel.NO_MEDIA,
    )


def _make_place(place_id: str = "osm:node:1") -> PlaceCandidate:
    return PlaceCandidate(
        id=place_id, lat=50.0, lon=18.0, name="Důl Anna",
        source_type="osm",
        tags={"ruins": "industrial", "historic": "mine"},
    )


def _make_intent() -> PromptIntent:
    return PromptIntent(
        original_prompt="opuštěné průmyslové oblasti v Horním Slezsku",
        mode=ExperienceMode.ABANDONED_INDUSTRIAL,
        confidence=0.9,
    )


# ---------------------------------------------------------------------------
# Ollama /api/generate response wrapper
# ---------------------------------------------------------------------------

def _ollama_response(inner: dict) -> dict:
    """Wrap inner JSON dict as Ollama /api/generate response."""
    return {"response": json.dumps(inner), "done": True}


# ---------------------------------------------------------------------------
# Test 1: happy path — Ollama returns valid JSON with confidence 0.8
# ---------------------------------------------------------------------------

async def test_happy_path_returns_llm_result(httpx_mock):
    """Ollama returns valid JSON with confidence 0.8 → used_llm=True."""
    httpx_mock.add_response(
        json=_ollama_response({
            "why_here": "Historická šachta odpovídá hledání průmyslových ruin.",
            "narration": "Důl Anna byl uhelný důl. Dnes je opuštěný.",
            "confidence": 0.8,
            "sources_used": ["osm_tags", "place_name"],
        })
    )

    provider = _make_provider()
    result = await provider.narrate_stop(_make_stop(), _make_place(), _make_intent())

    assert result.used_llm is True
    assert result.confidence == pytest.approx(0.8)
    assert "šachta" in result.why_here
    assert result.fallback_reason is None
    assert "osm_tags" in result.sources_used


# ---------------------------------------------------------------------------
# Test 2: low confidence → fallback (used_llm=False)
# ---------------------------------------------------------------------------

async def test_low_confidence_triggers_fallback(httpx_mock):
    """Confidence 0.3 < 0.4 threshold → used_llm=False, fallback_reason set."""
    httpx_mock.add_response(
        json=_ollama_response({
            "why_here": "Nejasná lokace.",
            "narration": "Málo dat.",
            "confidence": 0.3,
            "sources_used": [],
        })
    )

    provider = _make_provider()
    result = await provider.narrate_stop(_make_stop(), _make_place(), _make_intent())

    assert result.used_llm is False
    assert result.fallback_reason == "low_confidence"
    assert result.why_here == ""
    assert result.narration == ""


# ---------------------------------------------------------------------------
# Test 3: connection error → fallback with ollama_error reason
# ---------------------------------------------------------------------------

async def test_connection_error_returns_fallback(httpx_mock):
    """Ollama unavailable (connection refused) → NarrationResult with used_llm=False."""
    import httpx as _httpx
    httpx_mock.add_exception(_httpx.ConnectError("Connection refused"))

    provider = _make_provider()
    result = await provider.narrate_stop(_make_stop(), _make_place(), _make_intent())

    assert result.used_llm is False
    assert result.fallback_reason is not None
    assert "ollama_error" in result.fallback_reason
    assert result.why_here == ""


# ---------------------------------------------------------------------------
# Test 4: malformed JSON response → fallback, no exception raised
# ---------------------------------------------------------------------------

async def test_malformed_json_returns_fallback(httpx_mock):
    """Ollama returns non-JSON text → graceful fallback, no exception propagated."""
    httpx_mock.add_response(
        json={"response": "This is not JSON at all { broken", "done": True}
    )

    provider = _make_provider()
    result = await provider.narrate_stop(_make_stop(), _make_place(), _make_intent())

    assert result.used_llm is False
    assert result.fallback_reason is not None
    assert "ollama_error" in result.fallback_reason


# ---------------------------------------------------------------------------
# Test 5: cache hit — second call with same inputs does not make HTTP request
# ---------------------------------------------------------------------------

async def test_cache_hit_skips_http(httpx_mock):
    """Second call with same place_id + intent returns cached result without HTTP."""
    httpx_mock.add_response(
        json=_ollama_response({
            "why_here": "Důl odpovídá promptu.",
            "narration": "Opuštěný důl z 19. století.",
            "confidence": 0.75,
            "sources_used": ["osm_tags"],
        })
    )

    cache = _DictCache()
    provider = _make_provider(cache)
    stop = _make_stop()
    place = _make_place()
    intent = _make_intent()

    first = await provider.narrate_stop(stop, place, intent)
    assert first.used_llm is True

    # Second call — no more HTTP responses registered; would raise if called
    second = await provider.narrate_stop(stop, place, intent)
    assert second.why_here == first.why_here
    assert second.confidence == pytest.approx(first.confidence)


# ---------------------------------------------------------------------------
# Test 6: health_check returns True when model is listed
# ---------------------------------------------------------------------------

async def test_health_check_ok(httpx_mock):
    """GET /api/tags lists phi3.5 → health_check returns True."""
    httpx_mock.add_response(
        json={"models": [{"name": "phi3.5:latest"}, {"name": "mistral:latest"}]}
    )

    provider = _make_provider()
    assert await provider.health_check() is True


# ---------------------------------------------------------------------------
# Test 7: health_check returns False when model is not in list
# ---------------------------------------------------------------------------

async def test_health_check_model_not_found(httpx_mock):
    """GET /api/tags does not list phi3.5 → health_check returns False."""
    httpx_mock.add_response(
        json={"models": [{"name": "mistral:latest"}]}
    )

    provider = _make_provider()
    assert await provider.health_check() is False


# ---------------------------------------------------------------------------
# Test 8: health_check returns False on connection error
# ---------------------------------------------------------------------------

async def test_health_check_connection_error(httpx_mock):
    """Ollama unreachable → health_check returns False, never raises."""
    import httpx as _httpx
    httpx_mock.add_exception(_httpx.ConnectError("refused"))

    provider = _make_provider()
    assert await provider.health_check() is False


# ---------------------------------------------------------------------------
# Test 9: confidence clamped to [0.0, 1.0]
# ---------------------------------------------------------------------------

async def test_confidence_clamped(httpx_mock):
    """Ollama returns confidence > 1.0 → clamped to 1.0 in parsed result."""
    httpx_mock.add_response(
        json=_ollama_response({
            "why_here": "Místo odpovídá.",
            "narration": "Detailní popis.",
            "confidence": 1.5,
            "sources_used": ["osm_tags"],
        })
    )

    provider = _make_provider()
    result = await provider.narrate_stop(_make_stop(), _make_place(), _make_intent())

    assert result.used_llm is True
    assert result.confidence == pytest.approx(1.0)
