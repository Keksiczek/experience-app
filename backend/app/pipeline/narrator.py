from app.core.logging import get_logger
from app.models.experience import ExperienceStop
from app.models.intent import ExperienceMode, PromptIntent
from app.models.media import FallbackLevel
from app.models.place import PlaceCandidate

logger = get_logger(__name__)

_WHY_HERE_TEMPLATES: dict[ExperienceMode, str] = {
    ExperienceMode.ABANDONED_INDUSTRIAL: (
        "Toto místo odpovídá záměru průzkumu opuštěných průmyslových lokalit. "
        "OSM data naznačují {tag_summary}."
    ),
    ExperienceMode.SCENIC_ROADTRIP: (
        "Místo je zařazeno pro svůj krajinný potenciál. "
        "Dostupná data uvádějí {tag_summary}."
    ),
    ExperienceMode.REMOTE_LANDSCAPE: (
        "Lokalita odpovídá kritériím odlehlosti a přírodního charakteru. "
        "Data zdroje: {tag_summary}."
    ),
}

_FALLBACK_NARRATIONS: dict[FallbackLevel, str] = {
    FallbackLevel.FULL: "",          # Filled from data
    FallbackLevel.PARTIAL_MEDIA:
        "Fotografie pochází z archivu Wikimedia Commons. Mapillary v tomto místě nemá pokrytí.",
    FallbackLevel.NO_MEDIA:
        "Pro toto místo nejsou dostupná žádná média. Zastávka je zařazena na základě OSM dat.",
    FallbackLevel.LOW_CONTEXT:
        "Kontextová metadata nejsou k dispozici.",
    FallbackLevel.MINIMAL:
        "Dostupná jsou pouze základní souřadnicová data. Ostatní informace chybí.",
}


def _summarize_tags(tags: dict[str, str]) -> str:
    """Build a factual summary string from OSM tags. Never invents information."""
    relevant_keys = [
        "name", "historic", "ruins", "landuse", "natural", "man_made",
        "disused:man_made", "tourism", "place", "abandoned",
    ]
    parts = []
    for key in relevant_keys:
        if key in tags and tags[key] not in ("yes", "no", ""):
            parts.append(f"{key}={tags[key]}")
    if not parts:
        return "OSM tagy bez dalšího popisu"
    return ", ".join(parts[:4])


def narrate_stops(
    stops: list[ExperienceStop],
    place_map: dict[str, PlaceCandidate],
    intent: PromptIntent,
) -> list[ExperienceStop]:
    template = _WHY_HERE_TEMPLATES.get(intent.mode, "{tag_summary}")

    for stop in stops:
        place = place_map.get(stop.place_id)
        tags = place.tags if place else {}
        tag_summary = _summarize_tags(tags)

        stop.why_here = template.format(tag_summary=tag_summary)

        fallback_note = _FALLBACK_NARRATIONS.get(stop.fallback_level, "")
        if fallback_note:
            stop.narration = fallback_note
        else:
            name_note = f"Lokalita: {stop.name}." if stop.name else ""
            stop.narration = f"{name_note} {tag_summary}".strip()

    logger.info("narration_complete", stops=len(stops))
    return stops


def compose_summary(stops: list[ExperienceStop], intent: PromptIntent) -> str:
    """Summary is factual and derived from selected stops, not invented."""
    if not stops:
        return "Experience neobsahuje žádné zastávky."

    region_names = list({s.name.split(",")[0] for s in stops if s.name})
    stop_count = len(stops)
    no_media_count = sum(1 for s in stops if s.fallback_level == FallbackLevel.NO_MEDIA)

    parts = [
        f"Experience obsahuje {stop_count} zastávek.",
        f"Mód: {intent.mode.value}.",
    ]

    if intent.preferred_regions:
        parts.append(f"Region: {', '.join(intent.preferred_regions)}.")

    if no_media_count > 0:
        parts.append(
            f"{no_media_count} z {stop_count} zastávek nemá dostupná média."
        )

    return " ".join(parts)
