"""Experience pipeline job orchestrator.

Propagates warnings, decision_reasons, and degradation_reason through every
pipeline step so that weak outputs can be traced back to their root cause in
the GenerationMetadata of the returned Experience object.
"""

import uuid
from datetime import datetime, UTC

from app.cache.file_cache import FileCache
from app.core.config import settings
from app.core.logging import get_logger
from app.jobs.job_store import BaseJobStore, InMemoryJobStore
from app.jobs.metrics import compute_quality_metrics
from app.models.experience import Experience, ExperienceStop, GenerationMetadata, JobStatus
from app.pipeline.experience_composer import compose_experience
from app.pipeline.intent_parser import parse_intent
from app.pipeline.media_resolution import resolve_media
from app.pipeline.narrator import compose_summary, narrate_stops
from app.pipeline.place_discovery import TooFewPlacesError, discover_places
from app.pipeline.region_discovery import discover_regions
from app.providers.mapillary import MapillaryProvider
from app.providers.nominatim import NominatimProvider
from app.providers.osm import OverpassProvider
from app.providers.wikimedia import WikimediaProvider
from app.providers.wikidata import WikidataProvider

logger = get_logger(__name__)

_store: BaseJobStore | None = None


def _get_store() -> BaseJobStore:
    global _store
    if _store is None:
        if settings.mock_mode:
            _store = InMemoryJobStore()
        else:
            from app.jobs.sqlite_job_store import SQLiteJobStore
            _store = SQLiteJobStore()
    return _store


def get_experience(job_id: str) -> Experience | None:
    import asyncio
    return asyncio.get_event_loop().run_until_complete(_get_store().get(job_id))


async def get_experience_async(job_id: str) -> Experience | None:
    return await _get_store().get(job_id)


async def list_job_ids() -> list[str]:
    return await _get_store().list_ids()


async def create_job(prompt: str) -> Experience:
    job_id = str(uuid.uuid4())
    experience = Experience(
        id=job_id,
        prompt=prompt,
        job_status=JobStatus.PENDING,
        created_at=datetime.now(UTC),
    )
    await _get_store().save(experience)
    return experience


async def run_experience_job(experience: Experience) -> None:
    await _execute_pipeline(experience)


async def _execute_pipeline(experience: Experience) -> None:
    started_at = datetime.now(UTC)
    experience.job_status = JobStatus.RUNNING
    await _get_store().save(experience)

    cache = FileCache(settings.cache_dir)

    if settings.mock_mode:
        from app.core.mock_mode import (
            MockMapillaryProvider,
            MockNominatimProvider,
            MockOverpassProvider,
            MockWikimediaProvider,
        )
        nominatim = MockNominatimProvider(cache)
        overpass = MockOverpassProvider(cache)
        mapillary = MockMapillaryProvider(cache)
        wikimedia = MockWikimediaProvider(cache)
        wikidata: WikidataProvider | None = None   # skip Wikidata in mock mode
    else:
        nominatim = NominatimProvider(cache)
        overpass = OverpassProvider(cache)
        mapillary = MapillaryProvider(cache)
        wikimedia = WikimediaProvider(cache)
        wikidata = WikidataProvider(cache)

    metadata = GenerationMetadata(started_at=started_at)

    try:
        # ── [1] Intent ───────────────────────────────────────────────────────
        logger.info("pipeline_step", step="intent_parser", job_id=experience.id)
        intent = parse_intent(experience.prompt)

        if intent.confidence < 0.4:
            experience.quality_flags.append("low_confidence_intent")
            metadata.warnings.append(
                f"intent confidence={intent.confidence:.2f} — "
                f"reasons: {'; '.join(intent.confidence_reasons)}"
            )

        if "ambiguous_mode" in intent.parse_warnings:
            metadata.warnings.append(
                f"ambiguous mode detection: {'; '.join(intent.ambiguity_signals)}"
            )

        if not intent.preferred_regions:
            experience.quality_flags.append("no_region_specified")
            metadata.warnings.append("no region detected in prompt — using registry fallback")

        metadata.decision_reasons.append(
            f"intent: mode={intent.mode.value}, confidence={intent.confidence:.2f}, "
            f"regions={intent.preferred_regions}"
        )
        metadata.pipeline_steps.append("intent_parser")

        # ── [2] Region Discovery ─────────────────────────────────────────────
        logger.info("pipeline_step", step="region_discovery", job_id=experience.id)
        regions = await discover_regions(intent, nominatim)
        if not regions:
            await _fail(
                experience,
                "no_region_found",
                "Nelze určit region z promptu.",
                metadata,
                degradation_reason="region_discovery returned zero candidates",
            )
            return

        experience.selected_region = regions[0].name
        metadata.decision_reasons.append(
            f"region selected: {regions[0].name} (source={regions[0].source}, "
            f"confidence={regions[0].confidence:.2f}, "
            f"reasons={regions[0].decision_reasons})"
        )
        if regions[0].known_limitations:
            metadata.warnings.append(
                f"region '{regions[0].name}' known limitations: "
                + "; ".join(regions[0].known_limitations)
            )
        metadata.pipeline_steps.append("region_discovery")

        # ── [3] Place Discovery ──────────────────────────────────────────────
        logger.info("pipeline_step", step="place_discovery", job_id=experience.id)
        try:
            places, discovery_warnings = await discover_places(
                intent, regions, overpass
            )
        except TooFewPlacesError as e:
            metadata.warnings.extend(e.warnings)
            await _fail(
                experience,
                "too_few_places",
                str(e),
                metadata,
                degradation_reason=f"only {e.found} places found, minimum is {e.minimum}",
            )
            return

        metadata.warnings.extend(discovery_warnings)
        metadata.decision_reasons.append(
            f"place_discovery: {len(places)} unique candidates, "
            f"must_have={sum(1 for p in places if p.signal_strength == 'must_have')}, "
            f"strong={sum(1 for p in places if p.signal_strength == 'strong')}, "
            f"weak={sum(1 for p in places if p.signal_strength == 'weak')}"
        )

        # Degrade stops_target when place count is low
        effective_target = intent.estimated_stops
        if len(places) < settings.pipeline_ideal_places:
            effective_target = max(settings.pipeline_stops_min, len(places) - 1)
            intent = intent.model_copy(update={"estimated_stops": effective_target})
            degradation_msg = (
                f"stops_target reduced to {effective_target} "
                f"(only {len(places)} places found, ideal={settings.pipeline_ideal_places})"
            )
            metadata.warnings.append(degradation_msg)
            metadata.degradation_reason = degradation_msg
            logger.warning(
                "reduced_stops_target",
                reason="suboptimal_place_count",
                places=len(places),
                new_target=effective_target,
            )

        metadata.total_candidates_evaluated = len(places)
        metadata.pipeline_steps.append("place_discovery")

        # ── [4] Media Resolution ─────────────────────────────────────────────
        logger.info("pipeline_step", step="media_resolution", job_id=experience.id)
        media_map = await resolve_media(places, mapillary, wikimedia)
        no_media_count = sum(
            1 for _, (_, fl) in media_map.items()
            if fl.value in ("NO_MEDIA", "MINIMAL")
        )
        if no_media_count > 0:
            metadata.warnings.append(
                f"{no_media_count}/{len(places)} places have no media "
                "(Mapillary + Wikimedia both returned empty)"
            )
        metadata.pipeline_steps.append("media_resolution")

        # ── [5] Experience Composition ───────────────────────────────────────
        logger.info("pipeline_step", step="experience_composer", job_id=experience.id)
        stops = await compose_experience(intent, places, media_map, wikidata)
        if len(stops) < settings.pipeline_stops_min:
            await _fail(
                experience,
                "composer_no_stops",
                f"Pouze {len(stops)} zastávek splnilo threshold "
                f"(minimum {settings.pipeline_stops_min}).",
                metadata,
                degradation_reason=(
                    f"composer selected {len(stops)} stops — "
                    "all candidates scored below emergency threshold"
                ),
            )
            return

        threshold_tag = (
            "emergency"
            if any("emergency" in str(s.decision_reasons) for s in stops)
            else "normal"
        )
        metadata.decision_reasons.append(
            f"composer selected {len(stops)} stops (threshold={threshold_tag})"
        )
        metadata.route_coherence_applied = True
        metadata.route_style_used = intent.route_style
        metadata.decision_reasons.append(
            f"route_coherence: ordered by route_style={intent.route_style!r}"
        )
        metadata.pipeline_steps.append("experience_composer")

        # ── [6] Narration ────────────────────────────────────────────────────
        logger.info("pipeline_step", step="narrator", job_id=experience.id)
        place_map = {p.id: p for p in places}
        stops = narrate_stops(stops, place_map, intent)
        summary = compose_summary(stops, intent)
        metadata.pipeline_steps.append("narrator")

        # Quality flags and metrics
        _apply_quality_flags(experience, stops, metadata)
        experience.quality_metrics = compute_quality_metrics(stops, place_map)

        experience.stops = stops
        experience.summary = summary
        metadata.completed_at = datetime.now(UTC)
        experience.generation_metadata = metadata

        experience.job_status = (
            JobStatus.COMPLETED_WITH_WARNINGS
            if experience.quality_flags
            else JobStatus.COMPLETED
        )

        logger.info(
            "pipeline_complete",
            job_id=experience.id,
            stops=len(stops),
            quality_flags=experience.quality_flags,
            imagery_coverage=experience.quality_metrics.imagery_coverage_ratio,
            narration_confidence=experience.quality_metrics.narration_confidence,
            status=experience.job_status,
            pipeline_warnings=len(metadata.warnings),
        )

    except ValueError as e:
        await _fail(experience, "invalid_prompt", str(e), metadata)
    except Exception as e:
        logger.exception("pipeline_unexpected_error", job_id=experience.id, error=str(e))
        await _fail(experience, "internal_error", "Neočekávaná chyba pipeline.", metadata)

    await _get_store().save(experience)


async def _fail(
    experience: Experience,
    error_code: str,
    error_message: str,
    metadata: GenerationMetadata,
    degradation_reason: str | None = None,
) -> None:
    experience.job_status = JobStatus.FAILED
    experience.error_code = error_code
    experience.error_message = error_message
    if degradation_reason:
        metadata.degradation_reason = degradation_reason
    metadata.completed_at = datetime.now(UTC)
    experience.generation_metadata = metadata
    await _get_store().save(experience)
    logger.error(
        "pipeline_failed",
        job_id=experience.id,
        code=error_code,
        message=error_message,
        degradation_reason=degradation_reason,
    )


def _apply_quality_flags(
    experience: Experience,
    stops: list[ExperienceStop],
    metadata: GenerationMetadata,
) -> None:
    n = len(stops)

    if n < settings.pipeline_stops_target:
        experience.quality_flags.append("few_places")
        metadata.warnings.append(
            f"only {n} stops selected (target={settings.pipeline_stops_target})"
        )

    no_media = sum(
        1 for s in stops
        if s.fallback_level.value in ("NO_MEDIA", "MINIMAL")
    )
    if no_media / n > settings.pipeline_media_low_threshold:
        experience.quality_flags.append("low_media")
        metadata.warnings.append(
            f"low media coverage: {no_media}/{n} stops have no imagery"
        )

    weak_narration = sum(
        1 for s in stops
        if s.narration_confidence < settings.pipeline_narration_weak_threshold
    )
    if weak_narration / n > 0.5:
        experience.quality_flags.append("partial_narration")
        metadata.warnings.append(
            f"weak narration: {weak_narration}/{n} stops below confidence threshold "
            f"({settings.pipeline_narration_weak_threshold})"
        )

    emergency_stops = sum(1 for s in stops if s.emergency_threshold_used)
    if emergency_stops > 0:
        experience.quality_flags.append("emergency_threshold_used")
        metadata.warnings.append(
            f"{emergency_stops} stops selected via emergency score threshold"
        )
