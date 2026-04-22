"""Narration via local Ollama instance.

Communicates with Ollama /api/generate endpoint using JSON mode for structured output.
Falls back silently to template narration if unavailable or low-confidence.

This is a standalone class — it does not extend BaseProvider because it manages
caching with a domain-specific key (place_id + mode + prompt prefix) rather than
the generic params-dict key that BaseProvider.fetch() requires.
"""

import hashlib
import json
from typing import Any

import httpx

from app.cache.base import BaseCache
from app.core.logging import get_logger
from app.models.experience import ExperienceStop, NarrationResult
from app.models.intent import PromptIntent
from app.models.place import PlaceCandidate

logger = get_logger(__name__)

_TTL_SECONDS = 30 * 24 * 3600  # 30 days

_SYSTEM_PROMPT = (
    "You are a factual geo-narrator. Your task is to write a short narration for a place\n"
    "that matches a travel experience prompt.\n"
    "\n"
    "Rules:\n"
    "- Use ONLY facts from the provided place data. Do not invent distances, dates,\n"
    "  names, or historical claims not present in the input.\n"
    "- Write in the same language as the original_prompt field.\n"
    "- If the data is insufficient, write a shorter text and set confidence below 0.5.\n"
    "- Return ONLY valid JSON, no markdown, no explanation outside the JSON.\n"
    "\n"
    "Required output format:\n"
    "{\n"
    '  "why_here": "<1-2 sentences: why this place matches the prompt>",\n'
    '  "narration": "<3-5 sentences: factual description of the place>",\n'
    '  "confidence": <0.0-1.0>,\n'
    '  "sources_used": ["wikidata_description", "osm_tags", "place_name"]\n'
    "}"
)


class OllamaNarratorProvider:
    """Narration via local Ollama instance.

    Standalone class — does not extend BaseProvider. Manages its own cache
    with a key derived from (place_id, mode, prompt_prefix) rather than a
    generic params dict.

    Falls back to template narrator if Ollama is unavailable or returns
    low-confidence output. Never raises — always returns some narration.
    """

    def __init__(self, cache: BaseCache, base_url: str, model: str) -> None:
        self._cache = cache
        self._base_url = base_url.rstrip("/")
        self._model = model

    # ── Internal helpers ────────────────────────────────────────────────────

    def _narration_cache_key(self, place_id: str, mode: str, prompt_prefix: str) -> str:
        digest = hashlib.sha256(
            f"{place_id}:{mode}:{prompt_prefix}".encode()
        ).hexdigest()[:16]
        return f"ollama:narration:{digest}"

    def _build_user_prompt(
        self,
        stop: ExperienceStop,
        place: PlaceCandidate,
        intent: PromptIntent,
    ) -> str:
        wikidata = place.wikidata
        return (
            f"original_prompt: {intent.original_prompt}\n"
            f"mode: {intent.mode.value}\n"
            f"place_name: {place.name}\n"
            f"osm_tags: {json.dumps(place.tags, ensure_ascii=False)}\n"
            f"wikidata_description: {wikidata.description if wikidata else 'not available'}\n"
            f"wikidata_instance_of: {wikidata.instance_of if wikidata else []}\n"
            f"heritage_status: {wikidata.heritage_status if wikidata else 'none'}\n"
            f"mood_keywords: {intent.mood}\n"
            f"terrain_keywords: {intent.terrain}\n"
        )

    async def _call_ollama(self, user_prompt: str) -> dict[str, Any]:
        from app.core.config import settings

        payload = {
            "model": self._model,
            "prompt": f"{_SYSTEM_PROMPT}\n\n{user_prompt}",
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0.3,
                "top_p": 0.9,
                "num_predict": 300,
            },
        }

        async with httpx.AsyncClient(timeout=settings.ollama_timeout_seconds) as client:
            response = await client.post(
                f"{self._base_url}/api/generate",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        raw_text = data.get("response", "")
        return json.loads(raw_text)  # raises json.JSONDecodeError on malformed output

    def _parse_and_validate(self, raw: dict[str, Any]) -> NarrationResult:
        why_here = str(raw.get("why_here", ""))
        narration = str(raw.get("narration", ""))
        confidence = float(raw.get("confidence", 0.0))
        sources_used = list(raw.get("sources_used", []))

        confidence = max(0.0, min(1.0, confidence))

        return NarrationResult(
            why_here=why_here,
            narration=narration,
            confidence=confidence,
            sources_used=sources_used,
            used_llm=True,
        )

    # ── Public API ───────────────────────────────────────────────────────────

    async def narrate_stop(
        self,
        stop: ExperienceStop,
        place: PlaceCandidate,
        intent: PromptIntent,
    ) -> NarrationResult:
        cache_key = self._narration_cache_key(
            place.id,
            intent.mode.value,
            intent.original_prompt[:50],
        )

        cached = await self._cache.get(cache_key)
        if cached:
            return NarrationResult(**cached)

        try:
            user_prompt = self._build_user_prompt(stop, place, intent)
            raw_json = await self._call_ollama(user_prompt)
            result = self._parse_and_validate(raw_json)
        except Exception as e:
            logger.warning(
                "ollama_narration_failed",
                place=place.name,
                error=str(e),
            )
            return NarrationResult(
                why_here="",
                narration="",
                confidence=0.0,
                used_llm=False,
                fallback_reason=f"ollama_error: {type(e).__name__}",
            )

        if result.confidence < 0.4:
            return NarrationResult(
                why_here="",
                narration="",
                confidence=result.confidence,
                used_llm=False,
                fallback_reason="low_confidence",
            )

        await self._cache.set(cache_key, result.model_dump(), ttl=_TTL_SECONDS)
        return result

    async def health_check(self) -> bool:
        """Return True if Ollama is running and the configured model is available."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._base_url}/api/tags")
                resp.raise_for_status()
                data = resp.json()

            models = [m.get("name", "") for m in data.get("models", [])]
            return any(self._model in m for m in models)
        except Exception:
            return False
