from app.jobs.metrics import compute_quality_metrics
from app.models.experience import ExperienceStop
from app.models.media import FallbackLevel
from app.models.place import PlaceCandidate


def _stop(order: int, lat: float, lon: float, fallback: FallbackLevel, conf: float = 0.8) -> ExperienceStop:
    return ExperienceStop(
        id=f"s{order}", order=order, place_id=f"p{order}", lat=lat, lon=lon,
        name=f"Stop {order}", short_title=f"Stop {order}",
        why_here="x", narration="x",
        fallback_level=fallback,
        narration_confidence=conf,
    )


def _place(order: int, tags: dict) -> PlaceCandidate:
    return PlaceCandidate(
        id=f"p{order}", lat=0.0, lon=0.0, name=f"Place {order}", source_type="osm", tags=tags
    )


class TestComputeQualityMetrics:
    def test_empty_stops_returns_zero_metrics(self):
        m = compute_quality_metrics([], {})
        assert m.imagery_coverage_ratio == 0.0
        assert m.diversity_score == 0.0

    def test_imagery_coverage_ratio(self):
        stops = [
            _stop(1, 50.0, 19.0, FallbackLevel.FULL),
            _stop(2, 50.1, 19.1, FallbackLevel.NO_MEDIA),
            _stop(3, 50.2, 19.2, FallbackLevel.PARTIAL_MEDIA),
        ]
        m = compute_quality_metrics(stops, {})
        # 2 out of 3 have media
        assert abs(m.imagery_coverage_ratio - 2 / 3) < 0.01

    def test_fallback_distribution_counts(self):
        stops = [
            _stop(1, 50.0, 19.0, FallbackLevel.FULL),
            _stop(2, 50.1, 19.1, FallbackLevel.FULL),
            _stop(3, 50.2, 19.2, FallbackLevel.NO_MEDIA),
        ]
        m = compute_quality_metrics(stops, {})
        assert m.fallback_distribution["FULL"] == 2
        assert m.fallback_distribution["NO_MEDIA"] == 1

    def test_diversity_score_spread_stops(self):
        # Stops far apart should have higher diversity score
        stops = [
            _stop(1, 0.0, 0.0, FallbackLevel.NO_MEDIA),
            _stop(2, 10.0, 10.0, FallbackLevel.NO_MEDIA),
        ]
        m = compute_quality_metrics(stops, {})
        assert m.diversity_score > 0.5

    def test_diversity_score_clustered_stops(self):
        stops = [
            _stop(1, 50.0, 19.0, FallbackLevel.NO_MEDIA),
            _stop(2, 50.001, 19.001, FallbackLevel.NO_MEDIA),
        ]
        m = compute_quality_metrics(stops, {})
        assert m.diversity_score < 0.1

    def test_narration_confidence_averaged(self):
        stops = [
            _stop(1, 50.0, 19.0, FallbackLevel.FULL, conf=1.0),
            _stop(2, 50.1, 19.1, FallbackLevel.NO_MEDIA, conf=0.0),
        ]
        m = compute_quality_metrics(stops, {})
        assert abs(m.narration_confidence - 0.5) < 0.01

    def test_context_richness_scales_with_tags(self):
        stops = [_stop(1, 50.0, 19.0, FallbackLevel.FULL)]
        rich_place = _place(1, {
            "ruins": "industrial", "landuse": "industrial",
            "historic": "ruins", "man_made": "works",
            "building": "industrial", "abandoned": "yes",
            "start_date": "1890", "end_date": "1990",
        })
        m = compute_quality_metrics(stops, {"p1": rich_place})
        assert m.context_richness >= 0.75

    def test_context_richness_zero_for_empty_tags(self):
        stops = [_stop(1, 50.0, 19.0, FallbackLevel.NO_MEDIA)]
        empty_place = _place(1, {})
        m = compute_quality_metrics(stops, {"p1": empty_place})
        assert m.context_richness == 0.0
