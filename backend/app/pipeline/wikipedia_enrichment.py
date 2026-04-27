"""Enrich finalised stops with Wikipedia article summaries.

Runs after the narrator step.  For each stop whose `place_id` resolves to a
Wikidata QID (via the place's `wikidata.wikidata_id`), kick off a Wikipedia
summary fetch in parallel.  Results are written back to
`stop.wikipedia_summary` / `wikipedia_url` / `wikipedia_lang`.

This step never fails the pipeline — every error is logged and the stop is
left unchanged.  Throttled by an asyncio.Semaphore so we don't hammer the
Wikidata + Wikipedia endpoints with N parallel requests when N is large.
"""

from __future__ import annotations

import asyncio

from app.core.logging import get_logger
from app.models.experience import ExperienceStop
from app.models.place import PlaceCandidate
from app.providers.wikipedia import WikipediaProvider

logger = get_logger(__name__)

_WIKIPEDIA_CONCURRENCY = 3


async def enrich_with_wikipedia(
    stops: list[ExperienceStop],
    place_map: dict[str, PlaceCandidate],
    wikipedia: WikipediaProvider,
) -> int:
    """Mutate stops in place; return the count of stops that received text."""

    sem = asyncio.Semaphore(_WIKIPEDIA_CONCURRENCY)

    async def enrich_one(stop: ExperienceStop) -> bool:
        place = place_map.get(stop.place_id)
        async with sem:
            try:
                # Mock providers expose a name-based fallback so the pipeline
                # produces visible content without a real Wikidata enrichment
                # step.  Real provider keeps the QID-only contract.
                if hasattr(wikipedia, "fetch_summary_for_stop"):
                    result = await wikipedia.fetch_summary_for_stop(stop, place)
                else:
                    qid = (
                        place.wikidata.wikidata_id
                        if place and place.wikidata and place.wikidata.wikidata_id
                        else None
                    )
                    if not qid:
                        return False
                    result = await wikipedia.fetch_summary(qid)
            except Exception as e:  # noqa: BLE001 — never block pipeline
                logger.warning(
                    "wikipedia_enrich_failed",
                    stop_id=stop.id,
                    error=str(e),
                )
                return False
        if not result:
            return False
        stop.wikipedia_summary = result["summary"]
        stop.wikipedia_url = result["url"]
        stop.wikipedia_lang = result["lang"]
        # Surface the source link in the existing grounding list so the
        # frontend "OSM ↗ / Wikipedia ↗" row picks it up automatically.
        if result["url"] and result["url"] not in stop.grounding_sources:
            stop.grounding_sources.append(result["url"])

        # Translate Commons file titles into the same media_id format the
        # primary `media_id` uses so the frontend pipeline (media.thumbUrl)
        # can render them without special-casing.  Skip the title that
        # already matches the primary so we don't duplicate it.
        primary_title = (stop.media_id or "").split(":", 1)[1] if (
            stop.media_id and stop.media_id.startswith("wikimedia:")
        ) else None
        gallery = result.get("gallery") or []
        for raw_title in gallery:
            file_title = raw_title.replace(" ", "_")
            if primary_title and file_title == primary_title:
                continue
            media_id = f"wikimedia:{file_title}"
            if media_id not in stop.extra_media:
                stop.extra_media.append(media_id)
        return True

    flags = await asyncio.gather(*[enrich_one(s) for s in stops])
    enriched = sum(1 for f in flags if f)
    logger.info(
        "wikipedia_enrichment_complete",
        total=len(stops),
        enriched=enriched,
    )
    return enriched
