from app.models.experience import ExperienceStop
from app.models.intent import ExperienceMode, PromptIntent
from app.models.media import FallbackLevel
from app.models.place import PlaceCandidate
from app.pipeline.narrator import NarrationContext, narrate_stops


def _stop(place_id: str, fallback: FallbackLevel = FallbackLevel.NO_MEDIA) -> ExperienceStop:
    return ExperienceStop(
        id="s1", order=1, place_id=place_id, lat=50.0, lon=19.0,
        name="Test", short_title="Test", why_here="", narration="",
        fallback_level=fallback,
    )


def _place(place_id: str, tags: dict) -> PlaceCandidate:
    return PlaceCandidate(
        id=place_id, lat=50.0, lon=19.0, name="Test", source_type="osm", tags=tags
    )


def _intent() -> PromptIntent:
    return PromptIntent(
        original_prompt="test",
        mode=ExperienceMode.ABANDONED_INDUSTRIAL,
        themes=["abandoned_industrial"],
        confidence=0.9,
    )


class TestNarrationContext:
    def test_confidence_bare_no_tags(self):
        ctx = NarrationContext(name="", tags={}, fallback_level=FallbackLevel.MINIMAL)
        assert ctx.confidence == 0.0

    def test_confidence_one_tag(self):
        ctx = NarrationContext(name="X", tags={"ruins": "industrial"}, fallback_level=FallbackLevel.NO_MEDIA)
        assert ctx.confidence == 0.25

    def test_confidence_rich_context(self):
        ctx = NarrationContext(
            name="Důl Prokop",
            tags={"ruins": "industrial", "landuse": "industrial", "historic": "ruins", "man_made": "works"},
            fallback_level=FallbackLevel.FULL,
            wikidata_description="Abandoned coal mine from 19th century",
        )
        assert ctx.confidence == 1.0

    def test_meaningful_tags_excludes_name(self):
        ctx = NarrationContext(
            name="X",
            tags={"name": "X", "ruins": "industrial"},
            fallback_level=FallbackLevel.NO_MEDIA,
        )
        assert "name" not in ctx.meaningful_tags
        assert "ruins" in ctx.meaningful_tags


class TestNarrateStops:
    def test_bare_stop_produces_short_note(self):
        stops = [_stop("p1", FallbackLevel.MINIMAL)]
        place_map = {"p1": _place("p1", {})}
        result = narrate_stops(stops, place_map, _intent())
        # Bare: only coordinates note, no template prose
        assert result[0].narration_confidence == 0.0
        assert "Bez" in result[0].why_here or "souřadnicích" in result[0].why_here

    def test_full_context_uses_template(self):
        tags = {
            "ruins": "industrial", "landuse": "industrial",
            "historic": "ruins", "man_made": "works",
        }
        stops = [_stop("p1", FallbackLevel.FULL)]
        place_map = {"p1": _place("p1", tags)}
        result = narrate_stops(stops, place_map, _intent())
        assert result[0].narration_confidence >= 0.75
        # Template phrase should appear
        assert "průzkumu" in result[0].why_here or "OSM" in result[0].why_here

    def test_no_media_note_in_narration(self):
        stops = [_stop("p1", FallbackLevel.NO_MEDIA)]
        place_map = {"p1": _place("p1", {"ruins": "industrial", "landuse": "industrial"})}
        result = narrate_stops(stops, place_map, _intent())
        assert "média" in result[0].narration or "OSM" in result[0].narration

    def test_partial_media_note_mentions_wikimedia(self):
        stops = [_stop("p1", FallbackLevel.PARTIAL_MEDIA)]
        place_map = {"p1": _place("p1", {"ruins": "industrial", "landuse": "industrial"})}
        result = narrate_stops(stops, place_map, _intent())
        assert "Wikimedia" in result[0].narration

    def test_wikidata_description_included_when_available(self):
        tags = {"ruins": "industrial", "landuse": "industrial", "historic": "ruins", "man_made": "works"}
        stops = [_stop("p1", FallbackLevel.FULL)]
        place_map = {"p1": _place("p1", tags)}
        wikidata_map = {"p1": {"label": "Důl X", "description": "Historický důl z 19. století."}}
        result = narrate_stops(stops, place_map, _intent(), wikidata_map=wikidata_map)
        assert "19. století" in result[0].why_here

    def test_narration_confidence_written_to_stop(self):
        stops = [_stop("p1", FallbackLevel.NO_MEDIA)]
        place_map = {"p1": _place("p1", {"ruins": "industrial"})}
        result = narrate_stops(stops, place_map, _intent())
        assert 0.0 <= result[0].narration_confidence <= 1.0
