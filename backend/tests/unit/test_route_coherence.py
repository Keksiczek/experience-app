"""Unit tests for _order_stops route coherence logic.

Uses fixed coordinates so results are deterministic and verifiable by hand.
"""

import math

import pytest

from app.models.experience import ExperienceStop
from app.models.media import FallbackLevel
from app.pipeline.experience_composer import _order_stops


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_stop(lat: float, lon: float, idx: int = 0) -> ExperienceStop:
    return ExperienceStop(
        id=f"stop-{idx}",
        order=idx,
        stop_order=idx,
        place_id=f"place-{idx}",
        lat=lat,
        lon=lon,
        name=f"Stop {idx}",
        short_title=f"Stop {idx}",
        why_here="",
        narration="",
        fallback_level=FallbackLevel.NO_MEDIA,
    )


def _dist2(a: ExperienceStop, b: ExperienceStop) -> float:
    dlat = a.lat - b.lat
    dlon = a.lon - b.lon
    return dlat * dlat + dlon * dlon


# ---------------------------------------------------------------------------
# Test 1: linear ordering — west → east
# ---------------------------------------------------------------------------

def test_linear_orders_west_to_east():
    """5 stops spread mainly E–W → ordered west→east by lon."""
    stops = [
        _make_stop(50.0, 18.5, 0),
        _make_stop(50.0, 16.0, 1),
        _make_stop(50.0, 17.0, 2),
        _make_stop(50.0, 18.0, 3),
        _make_stop(50.0, 16.5, 4),
    ]
    ordered = _order_stops(stops, "linear")

    assert len(ordered) == 5
    lons = [s.lon for s in ordered]
    assert lons == sorted(lons), f"Expected west→east, got lons={lons}"


def test_linear_orders_south_to_north():
    """5 stops spread mainly N–S → ordered south→north by lat."""
    stops = [
        _make_stop(52.0, 18.0, 0),
        _make_stop(48.0, 18.1, 1),
        _make_stop(50.0, 18.05, 2),
        _make_stop(51.0, 18.0, 3),
        _make_stop(49.0, 18.1, 4),
    ]
    ordered = _order_stops(stops, "linear")

    lats = [s.lat for s in ordered]
    assert lats == sorted(lats), f"Expected south→north, got lats={lats}"


def test_linear_sets_stop_order():
    """stop_order field is set to 0-indexed position in final list."""
    stops = [_make_stop(50.0, 18.0 + i * 0.5, i) for i in range(5)]
    ordered = _order_stops(stops, "linear")
    assert [s.stop_order for s in ordered] == list(range(5))


# ---------------------------------------------------------------------------
# Test 2: loop ordering — first and last are nearest neighbours
# ---------------------------------------------------------------------------

def test_loop_closes_circuit():
    """5 stops on a regular pentagon — nearest-neighbor path closes the loop.

    Pentagon centred at (50.0, 18.0) with r=0.2°.
    The last stop visited by the nearest-neighbor algorithm should be
    the one geographically nearest to the first stop among all remaining
    stops (i.e., the loop closure is tight).
    """
    n = 5
    r = 0.2
    stops = []
    for i in range(n):
        angle = 2 * math.pi * i / n
        lat = 50.0 + r * math.cos(angle)
        lon = 18.0 + r * math.sin(angle)
        stops.append(_make_stop(lat, lon, i))

    ordered = _order_stops(stops, "loop")

    assert len(ordered) == n

    first = ordered[0]
    last = ordered[-1]
    intermediates = ordered[1:-1]

    d_last_to_first = _dist2(last, first)
    for mid in intermediates:
        d_last_to_mid = _dist2(last, mid)
        assert d_last_to_first <= d_last_to_mid + 1e-9, (
            f"Last stop should be nearest to first (loop closure). "
            f"d(last,first)={d_last_to_first:.6f} > d(last,{mid.id})={d_last_to_mid:.6f}"
        )


def test_loop_sets_stop_order():
    """stop_order is 0-indexed regardless of original order."""
    stops = [_make_stop(50.0, 18.0 + i * 0.1, i) for i in range(4)]
    ordered = _order_stops(stops, "loop")
    assert [s.stop_order for s in ordered] == list(range(4))


# ---------------------------------------------------------------------------
# Test 3: scattered — original order preserved
# ---------------------------------------------------------------------------

def test_scattered_preserves_original_order():
    """scattered route_style must not reorder stops."""
    stops = [
        _make_stop(50.0, 18.0, 0),
        _make_stop(48.0, 15.0, 1),
        _make_stop(52.0, 20.0, 2),
        _make_stop(49.0, 17.0, 3),
        _make_stop(51.0, 19.0, 4),
    ]
    original_ids = [s.id for s in stops]
    ordered = _order_stops(stops, "scattered")

    assert [s.id for s in ordered] == original_ids, (
        f"scattered should preserve order. Expected {original_ids}, "
        f"got {[s.id for s in ordered]}"
    )


def test_scattered_sets_stop_order():
    stops = [_make_stop(50.0, 18.0 + i * 0.5, i) for i in range(3)]
    ordered = _order_stops(stops, "scattered")
    assert [s.stop_order for s in ordered] == [0, 1, 2]


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_single_stop_any_style():
    """Single stop is returned unchanged for all route styles."""
    stop = _make_stop(50.0, 18.0, 0)
    for style in ("linear", "loop", "scattered", "unknown"):
        result = _order_stops([stop], style)
        assert len(result) == 1
        assert result[0].stop_order == 0


def test_unknown_route_style_falls_back_to_scattered():
    """Unrecognised route_style preserves original order."""
    stops = [_make_stop(50.0, float(i), i) for i in range(3)]
    original_ids = [s.id for s in stops]
    ordered = _order_stops(stops, "point_to_point")
    assert [s.id for s in ordered] == original_ids
