from dataclasses import dataclass, field
from app.core.logging import get_logger
from app.models.experience import ExperienceStop
from app.models.intent import ExperienceMode, PromptIntent
from app.models.media import FallbackLevel
from app.models.place import PlaceCandidate

logger = get_logger(__name__)

# Minimum number of meaningful OSM tags required for a non-trivial narration.
# Below this, the narrator produces a one-line factual note instead of a template sentence.
_MIN_TAGS_FOR_FULL_NARRATION = 2

_WHY_HERE_TEMPLATES: dict[ExperienceMode, str] = {
    ExperienceMode.ABANDONED_INDUSTRIAL: (
        "Toto místo odpovídá záměru průzkumu opuštěných průmyslových lokalit. "
        "OSM data uvádějí: {tag_summary}."
    ),
    ExperienceMode.SCENIC_ROADTRIP: (
        "Místo je zařazeno pro svůj krajinný potenciál. "
        "Dostupná data uvádějí: {tag_summary}."
    ),
    ExperienceMode.REMOTE_LANDSCAPE: (
        "Lokalita odpovídá kritériím odlehlosti a přírodního charakteru. "
        "OSM data: {tag_summary}."
    ),
}

_MEDIA_NOTES: dict[FallbackLevel, str] = {
    FallbackLevel.FULL: "",
    FallbackLevel.PARTIAL_MEDIA:
        "Fotografie pochází z archivu Wikimedia Commons (Mapillary bez pokrytí).",
    FallbackLevel.NO_MEDIA:
        "Žádná média nejsou k dispozici. Zastávka je zařazena pouze na základě OSM dat.",
    FallbackLevel.LOW_CONTEXT:
        "Kontextová metadata nejsou dostupná.",
    FallbackLevel.MINIMAL:
        "K dispozici jsou pouze základní souřadnicová data.",
}


@dataclass
class NarrationContext:
    """Captures exactly what facts are available for one stop. Nothing is invented."""
    name: str
    tags: dict[str, str]
    fallback_level: FallbackLevel
    wikidata_label: str = ""
    wikidata_description: str = ""
    heritage_status: str | None = None

    @property
    def meaningful_tags(self) -> dict[str, str]:
        skip = {"source", "name", "name:en", "name:cs"}
        return {k: v for k, v in self.tags.items() if k not in skip and v not in ("yes", "no", "")}

    @property
    def confidence(self) -> float:
        """
        Narration confidence based on available structured data.
        This score is objective — derived purely from what the providers returned.

        0.0  bare: only coordinates, no tags
        0.25 minimal: 1 meaningful tag
        0.50 partial: 2–3 tags, no wikidata
        0.75 good: 4+ tags or wikidata description
        1.0  full: tags + wikidata + name
        """
        tag_count = len(self.meaningful_tags)
        has_wikidata = bool(self.wikidata_description)
        has_name = bool(self.name and self.name != f"OSM node {self.name}")

        if tag_count == 0:
            return 0.0   # bare: no OSM tags regardless of name
        if tag_count == 1 and not has_wikidata:
            return 0.25
        if tag_count <= 3 and not has_wikidata:
            return 0.50
        if tag_count >= 4 or has_wikidata:
            return 0.75 + (0.25 if has_name else 0.0)
        return 0.50


def _build_tag_summary(ctx: NarrationContext) -> str:
    """Factual tag summary. Uses only what is in ctx.tags — never invents."""
    ordered_keys = [
        "historic", "ruins", "landuse", "natural", "man_made",
        "disused:man_made", "tourism", "place",
    ]
    parts = []
    for key in ordered_keys:
        val = ctx.tags.get(key)
        if val and val not in ("yes", "no", ""):
            parts.append(f"{key}={val}")

    if not parts:
        return "bez dalšího popisu v OSM"
    return ", ".join(parts[:4])


def _build_why_here(ctx: NarrationContext, mode: ExperienceMode) -> str:
    """
    Grounded why_here: only states facts from ctx.
    Falls back to shorter factual note when context is weak.

    If ctx.wikidata_description is set, it is used as the primary basis
    of the sentence (instead of the generic mode template).
    If heritage_status == "listed", appends "Kulturní památka."
    """
    if ctx.confidence < 0.25:
        return f"Lokalita na souřadnicích ({ctx.name or 'bez názvu'}). Bez dostupných OSM dat."

    tag_summary = _build_tag_summary(ctx)

    if ctx.confidence < 0.50 or len(ctx.meaningful_tags) < _MIN_TAGS_FOR_FULL_NARRATION:
        # Minimal context — one factual line, no template sentence
        text = f"OSM záznam: {tag_summary}."
    elif ctx.wikidata_description:
        # Wikidata description available — use it as the primary sentence
        text = ctx.wikidata_description
    else:
        template = _WHY_HERE_TEMPLATES.get(mode, "OSM data: {tag_summary}.")
        text = template.format(tag_summary=tag_summary)

    if ctx.heritage_status == "listed":
        text += " Kulturní památka."

    return text


def _build_narration(ctx: NarrationContext) -> str:
    """
    Narration = media note + optional name context.
    Never speculates beyond what ctx contains.
    """
    media_note = _MEDIA_NOTES.get(ctx.fallback_level, "")
    name_part = f"Lokalita: {ctx.name}." if ctx.name else ""

    if not name_part and not media_note:
        return "Žádná další data nejsou k dispozici."

    parts = [p for p in [name_part, media_note] if p]
    return " ".join(parts)


def narrate_stops(
    stops: list[ExperienceStop],
    place_map: dict[str, PlaceCandidate],
    intent: PromptIntent,
    wikidata_map: dict[str, dict[str, str]] | None = None,
) -> list[ExperienceStop]:
    wikidata_map = wikidata_map or {}
    weak_narration_count = 0

    for stop in stops:
        place = place_map.get(stop.place_id)
        wd = wikidata_map.get(stop.place_id, {})

        # Prefer Wikidata context from place.wikidata (enriched during discovery)
        # over the legacy wikidata_map dict parameter.
        wikidata_desc = ""
        wikidata_label = ""
        heritage_status: str | None = None

        if place is not None and place.wikidata is not None:
            wikidata_desc = place.wikidata.description or ""
            heritage_status = place.wikidata.heritage_status
            wikidata_label = (
                place.wikidata.raw_labels.get("cs")
                or place.wikidata.raw_labels.get("en")
                or ""
            )
        elif wd:
            wikidata_desc = wd.get("description", "")
            wikidata_label = wd.get("label", "")

        ctx = NarrationContext(
            name=stop.name,
            tags=place.tags if place else {},
            fallback_level=stop.fallback_level,
            wikidata_label=wikidata_label,
            wikidata_description=wikidata_desc,
            heritage_status=heritage_status,
        )

        stop.why_here = _build_why_here(ctx, intent.mode)
        stop.narration = _build_narration(ctx)
        stop.narration_confidence = ctx.confidence

        if ctx.confidence < 0.50:
            weak_narration_count += 1

    if weak_narration_count > 0:
        logger.warning(
            "weak_narration_stops",
            count=weak_narration_count,
            total=len(stops),
        )

    logger.info("narration_complete", stops=len(stops), weak=weak_narration_count)
    return stops


def compose_summary(stops: list[ExperienceStop], intent: PromptIntent) -> str:
    """Summary is factual and derived only from selected stops."""
    if not stops:
        return "Experience neobsahuje žádné zastávky."

    stop_count = len(stops)
    no_media_count = sum(1 for s in stops if s.fallback_level == FallbackLevel.NO_MEDIA)
    weak_count = sum(1 for s in stops if s.narration_confidence < 0.50)

    parts = [
        f"Experience obsahuje {stop_count} zastávek.",
        f"Mód: {intent.mode.value}.",
    ]

    if intent.preferred_regions:
        parts.append(f"Region: {', '.join(intent.preferred_regions)}.")

    if no_media_count > 0:
        parts.append(f"{no_media_count} z {stop_count} zastávek nemá dostupná média.")

    if weak_count > 0:
        parts.append(
            f"{weak_count} zastávek má omezený kontext (jen základní OSM data)."
        )

    return " ".join(parts)
