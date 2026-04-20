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

logger = get_logger(__name__)

# Module-level store. Replace with a persistent store before production use.
# See job_store.py for the full list of in-memory limitations.
_store: BaseJobStore = InMemoryJobStore()


def get_experience(job_id: str) -> Experience | None:
    import asyncio
    return asyncio.get_event_loop().run_until_complete(_store.get(job_id))


async def get_experience_async(job_id: str) -> Experience | None:
    return await _store.get(job_id)


async def create_job(prompt: str) -> Experience:
    job_id = str(uuid.uuid4())
    experience = Experience(id=job_id, prompt=prompt, job_status=JobStatus.PENDING)
    await _store.save(experience)
    return experience


async def run_experience_job(experience: Experience) -> None:
    await _execute_pipeline(experience)


async def _execute_pipeline(experience: Experience) -> None:
    started_at = datetime.now(UTC)
    experience.job_status = JobStatus.RUNNING
    await _store.save(experience)

    cache = FileCache(settings.cache_dir)
    nominatim = NominatimProvider(cache)
    overpass = OverpassProvider(cache)
    mapillary = MapillaryProvider(cache)
    wikimedia = WikimediaProvider(cache)

    metadata = GenerationMetadata(started_at=started_at)

    try:
        # [1] Intent
        logger.info("pipeline_step", step="intent_parser", job_id=experience.id)
        intent = parse_intent(experience.prompt)
        if intent.confidence < 0.4:
            experience.quality_flags.append("low_confidence_intent")
        if not intent.preferred_regions:
            experience.quality_flags.append("no_region_specified")
        metadata.pipeline_steps.append("intent_parser")

        # [2] Region Discovery
        logger.info("pipeline_step", step="region_discovery", job_id=experience.id)
        regions = await discover_regions(intent, nominatim)
        if not regions:
            await _fail(experience, "no_region_found", "Nelze určit region z promptu.", metadata)
            return
        experience.selected_region = regions[0].name
        metadata.pipeline_steps.append("region_discovery")

        # [3] Place Discovery
        logger.info("pipeline_step", step="place_discovery", job_id=experience.id)
        try:
            places = await discover_places(intent, regions, overpass)
        except TooFewPlacesError as e:
            await _fail(experience, "too_few_places", str(e), metadata)
            return

        # Degrade stops_target when place count is low — produce a shorter but valid experience
        # rather than forcing the composer to emergency-threshold everything
        effective_target = intent.estimated_stops
        if len(places) < settings.pipeline_ideal_places:
            effective_target = max(settings.pipeline_stops_min, len(places) - 1)
            intent = intent.model_copy(update={"estimated_stops": effective_target})
            logger.warning(
                "reduced_stops_target",
                reason="suboptimal_place_count",
                places=len(places),
                new_target=effective_target,
            )

        metadata.total_candidates_evaluated = len(places)
        metadata.pipeline_steps.append("place_discovery")

        # [4] Media Resolution
        logger.info("pipeline_step", step="media_resolution", job_id=experience.id)
        media_map = await resolve_media(places, mapillary, wikimedia)
        metadata.pipeline_steps.append("media_resolution")

        # [5] Experience Composition
        logger.info("pipeline_step", step="experience_composer", job_id=experience.id)
        stops = compose_experience(intent, places, media_map)
        if len(stops) < settings.pipeline_stops_min:
            await _fail(
                experience,
                "composer_no_stops",
                f"Pouze {len(stops)} zastávek splnilo threshold (minimum {settings.pipeline_stops_min}).",
                metadata,
            )
            return
        metadata.pipeline_steps.append("experience_composer")

        # [6] Narration
        logger.info("pipeline_step", step="narrator", job_id=experience.id)
        place_map = {p.id: p for p in places}
        stops = narrate_stops(stops, place_map, intent)
        summary = compose_summary(stops, intent)
        metadata.pipeline_steps.append("narrator")

        # Quality flags and metrics
        _apply_quality_flags(experience, stops)
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
        )

    except ValueError as e:
        await _fail(experience, "invalid_prompt", str(e), metadata)
    except Exception as e:
        logger.exception("pipeline_unexpected_error", job_id=experience.id, error=str(e))
        await _fail(experience, "internal_error", "Neočekávaná chyba pipeline.", metadata)

    await _store.save(experience)


async def _fail(
    experience: Experience,
    error_code: str,
    error_message: str,
    metadata: GenerationMetadata,
) -> None:
    experience.job_status = JobStatus.FAILED
    experience.error_code = error_code
    experience.error_message = error_message
    metadata.completed_at = datetime.now(UTC)
    experience.generation_metadata = metadata
    await _store.save(experience)
    logger.error("pipeline_failed", job_id=experience.id, code=error_code, message=error_message)


def _apply_quality_flags(experience: Experience, stops: list[ExperienceStop]) -> None:
    n = len(stops)

    if n < settings.pipeline_stops_target:
        experience.quality_flags.append("few_places")

    no_media = sum(
        1 for s in stops
        if s.fallback_level.value in ("NO_MEDIA", "MINIMAL")
    )
    if no_media / n > settings.pipeline_media_low_threshold:
        experience.quality_flags.append("low_media")

    weak_narration = sum(
        1 for s in stops
        if s.narration_confidence < settings.pipeline_narration_weak_threshold
    )
    if weak_narration / n > 0.5:
        experience.quality_flags.append("partial_narration")
