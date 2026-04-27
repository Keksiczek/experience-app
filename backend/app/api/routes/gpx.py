"""GPX 1.1 export for an Experience.

Produces standard GPX so the trip can be opened in OsmAnd, Locus, Strava,
Komoot etc.  Each stop becomes a waypoint with the narration as description,
and the sequence of stops is also exposed as a single track segment so apps
that only follow `<trk>` (not `<wpt>`) still draw the route.

Loop routes (route_style_used == "loop") have the first point appended to
close the polygon; other styles emit an open polyline.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from app.models.experience import Experience

GPX_NAMESPACE = "http://www.topografix.com/GPX/1/1"


def _coord_attrs(lat: float, lon: float) -> dict[str, str]:
    # GPX wants 6+ decimal places for sub-meter precision.
    return {"lat": f"{lat:.6f}", "lon": f"{lon:.6f}"}


def _stop_description(stop) -> str:
    parts = [stop.why_here, stop.narration]
    return "\n\n".join(p for p in parts if p)


def build_gpx(exp: Experience) -> str:
    """Render the experience as a GPX 1.1 XML string (UTF-8)."""

    ET.register_namespace("", GPX_NAMESPACE)
    gpx = ET.Element(
        "gpx",
        {
            "version": "1.1",
            "creator": "experience-app",
            "xmlns": GPX_NAMESPACE,
        },
    )

    # ── Metadata block ───────────────────────────────────────────────────
    metadata = ET.SubElement(gpx, "metadata")
    name_el = ET.SubElement(metadata, "name")
    name_el.text = exp.prompt or f"Experience {exp.id[:8]}"
    if exp.summary:
        desc_el = ET.SubElement(metadata, "desc")
        desc_el.text = exp.summary
    if exp.created_at is not None:
        time_el = ET.SubElement(metadata, "time")
        time_el.text = exp.created_at.isoformat()

    # ── Waypoints ────────────────────────────────────────────────────────
    sorted_stops = sorted(
        (s for s in exp.stops if s.lat is not None and s.lon is not None),
        key=lambda s: s.stop_order,
    )

    for stop in sorted_stops:
        wpt = ET.SubElement(gpx, "wpt", _coord_attrs(stop.lat, stop.lon))
        wpt_name = ET.SubElement(wpt, "name")
        wpt_name.text = stop.short_title or stop.name or f"Stop {stop.stop_order + 1}"
        desc_text = _stop_description(stop)
        if desc_text:
            desc_el = ET.SubElement(wpt, "desc")
            desc_el.text = desc_text
        # Keep numeric grouping aware of the order — useful for apps that
        # show waypoint indices.
        sym = ET.SubElement(wpt, "sym")
        sym.text = "Waypoint"

    # ── Track (so apps that only consume <trk> still draw the route) ─────
    if len(sorted_stops) >= 2:
        trk = ET.SubElement(gpx, "trk")
        trk_name = ET.SubElement(trk, "name")
        trk_name.text = exp.prompt or f"Experience {exp.id[:8]}"
        trkseg = ET.SubElement(trk, "trkseg")

        track_points = list(sorted_stops)
        route_style = (
            exp.generation_metadata.route_style_used
            if exp.generation_metadata
            else None
        )
        if route_style == "loop":
            track_points.append(sorted_stops[0])

        for stop in track_points:
            ET.SubElement(trkseg, "trkpt", _coord_attrs(stop.lat, stop.lon))

    body = ET.tostring(gpx, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + body
