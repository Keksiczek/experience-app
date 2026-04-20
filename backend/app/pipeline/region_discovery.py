"""Region Discovery V2.

Selection priority:
1. If prompt named a region explicitly → try Nominatim geocoding.
2. If Nominatim succeeds → return those results, enriched with registry metadata.
3. If Nominatim fails or prompt has no region → scan registry for mode-compatible
   regions, scored by alias match + mode fit.
4. If registry yields nothing → fall back to legacy static JSON (last resort).

Decision reasons are attached to every returned RegionCandidate.
No false certainty: registry fallbacks use lower confidence values.
"""

import json
from pathlib import Path

import yaml

from app.core.logging import get_logger
from app.models.intent import ExperienceMode, PromptIntent
from app.models.place import RegionCandidate
from app.providers.nominatim import NominatimProvider

logger = get_logger(__name__)

_REGISTRY_PATH = (
    Path(__file__).parent.parent.parent.parent / "data" / "regions" / "region_registry.yaml"
)
_STATIC_FALLBACK_PATH = (
    Path(__file__).parent.parent.parent.parent / "data" / "samples" / "regions.json"
)


# ---------------------------------------------------------------------------
# Registry loading (cached at import time after first call)
# ---------------------------------------------------------------------------

_registry_cache: list[dict] | None = None


def _load_registry() -> list[dict]:
    global _registry_cache
    if _registry_cache is not None:
        return _registry_cache
    if not _REGISTRY_PATH.exists():
        logger.warning("region_registry_missing", path=str(_REGISTRY_PATH))
        _registry_cache = []
        return _registry_cache
    try:
        with open(_REGISTRY_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        _registry_cache = data.get("regions", [])
    except Exception as e:
        logger.error("region_registry_load_error", path=str(_REGISTRY_PATH), error=str(e))
        _registry_cache = []
    return _registry_cache


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def discover_regions(
    intent: PromptIntent,
    nominatim: NominatimProvider,
) -> list[RegionCandidate]:
    """Return ordered list of RegionCandidates.  Empty list = hard fail."""

    # 1. Try Nominatim for explicitly named regions
    if intent.preferred_regions:
        nominatim_results = await _try_nominatim(intent, nominatim)
        if nominatim_results:
            return nominatim_results

    # 2. Registry-based selection (mode + alias matching)
    registry_results = _select_from_registry(intent)
    if registry_results:
        return registry_results

    # 3. Legacy static JSON (last resort)
    static_results = _load_static_fallback(intent)
    if static_results:
        logger.warning(
            "region_static_fallback_used",
            mode=intent.mode.value,
            preferred=intent.preferred_regions,
        )
        return static_results

    logger.error(
        "region_discovery_failed",
        preferred_regions=intent.preferred_regions,
        mode=intent.mode.value,
    )
    return []


# ---------------------------------------------------------------------------
# Step 1: Nominatim
# ---------------------------------------------------------------------------


async def _try_nominatim(
    intent: PromptIntent,
    nominatim: NominatimProvider,
) -> list[RegionCandidate]:
    candidates: list[RegionCandidate] = []
    registry = _load_registry()

    for region_name in intent.preferred_regions:
        results = await nominatim.geocode_region(region_name)
        if not results:
            continue
        # Take the best Nominatim hit and enrich from registry if possible
        best = results[0]
        registry_entry = _find_registry_entry(region_name, registry)
        candidate = _enrich_from_registry(best, registry_entry, reason_prefix="nominatim")
        candidate.decision_reasons.append(
            f"geocoded via Nominatim for prompt region '{region_name}'"
        )
        candidates.append(candidate)
        logger.info("region_found", source="nominatim", region=region_name)

    return candidates


# ---------------------------------------------------------------------------
# Step 2: Registry selection
# ---------------------------------------------------------------------------


def _select_from_registry(intent: PromptIntent) -> list[RegionCandidate]:
    registry = _load_registry()
    if not registry:
        return []

    mode_value = intent.mode.value
    search_terms = [r.lower() for r in intent.preferred_regions]

    scored: list[tuple[float, list[str], dict]] = []

    for entry in registry:
        score = 0.0
        reasons: list[str] = []

        # Mode fit (required — exclude regions that don't support the mode)
        supported = [m.lower() for m in entry.get("supported_modes", [])]
        if mode_value not in supported:
            continue
        score += 3.0
        reasons.append(f"supports mode {mode_value}")

        # Alias / name match to prompt regions
        aliases = [a.lower() for a in entry.get("aliases", [])]
        name_lower = entry.get("name", "").lower()
        for term in search_terms:
            if term in name_lower or any(term in a for a in aliases):
                score += 5.0
                reasons.append(f"alias match for prompt term '{term}'")

        # Prefer higher expected media coverage
        coverage = entry.get("expected_media_coverage", "unknown")
        if coverage == "high":
            score += 1.0
            reasons.append("high expected_media_coverage")
        elif coverage == "medium":
            score += 0.5
            reasons.append("medium expected_media_coverage")

        # Penalise known limitation count
        limitations = entry.get("known_limitations", [])
        score -= 0.3 * len(limitations)
        if limitations:
            reasons.append(f"{len(limitations)} known limitation(s)")

        scored.append((score, reasons, entry))

    if not scored:
        return []

    scored.sort(key=lambda x: x[0], reverse=True)

    results: list[RegionCandidate] = []
    for rank, (sc, reasons, entry) in enumerate(scored[:2]):
        # Confidence: registry selection is inherently less certain than geocoding
        base_confidence = min(0.85, 0.5 + sc * 0.05) if sc > 3 else 0.4
        decision_reasons = list(reasons)
        decision_reasons.append(f"registry rank {rank + 1}, score={sc:.1f}")

        bbox = entry.get("bbox", [0, 0, 0, 0])
        candidate = RegionCandidate(
            region_id=entry.get("region_id", ""),
            name=entry["name"],
            lat_min=float(bbox[0]),
            lon_min=float(bbox[1]),
            lat_max=float(bbox[2]),
            lon_max=float(bbox[3]),
            source="registry",
            confidence=round(base_confidence, 2),
            country=entry.get("country", ""),
            supported_modes=entry.get("supported_modes", []),
            expected_media_coverage=entry.get("expected_media_coverage", "unknown"),
            known_limitations=entry.get("known_limitations", []),
            decision_reasons=decision_reasons,
        )
        results.append(candidate)
        logger.info(
            "region_found",
            source="registry",
            region=candidate.name,
            confidence=candidate.confidence,
            reasons=reasons_list,
        )

    return results


# ---------------------------------------------------------------------------
# Step 3: Static JSON fallback
# ---------------------------------------------------------------------------


def _load_static_fallback(intent: PromptIntent) -> list[RegionCandidate]:
    if not _STATIC_FALLBACK_PATH.exists():
        return []
    try:
        with open(_STATIC_FALLBACK_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []

    mode_value = intent.mode.value
    search_terms = [r.lower() for r in intent.preferred_regions] + [mode_value]
    results = []

    for region in data.get("regions", []):
        name = region.get("name", "").lower()
        aliases = [a.lower() for a in region.get("aliases", [])]
        mode_hints = [h.lower() for h in region.get("mode_hints", [])]
        if not (
            any(term in name or term in aliases for term in search_terms)
            or mode_value in mode_hints
        ):
            continue
        bbox = region["bbox"]
        results.append(
            RegionCandidate(
                name=region["name"],
                lat_min=bbox[0],
                lon_min=bbox[1],
                lat_max=bbox[2],
                lon_max=bbox[3],
                source="static_fallback",
                confidence=0.35,
                decision_reasons=["selected from legacy static JSON (last resort fallback)"],
            )
        )

    return results[:2]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_registry_entry(region_name: str, registry: list[dict]) -> dict | None:
    name_lower = region_name.lower()
    for entry in registry:
        if name_lower in entry.get("name", "").lower():
            return entry
        if any(name_lower in a.lower() for a in entry.get("aliases", [])):
            return entry
    return None


def _enrich_from_registry(
    candidate: RegionCandidate,
    entry: dict | None,
    reason_prefix: str,
) -> RegionCandidate:
    if entry is None:
        return candidate
    return candidate.model_copy(
        update={
            "region_id": entry.get("region_id", candidate.region_id),
            "country": entry.get("country", candidate.country),
            "supported_modes": entry.get("supported_modes", candidate.supported_modes),
            "expected_media_coverage": entry.get(
                "expected_media_coverage", candidate.expected_media_coverage
            ),
            "known_limitations": entry.get("known_limitations", candidate.known_limitations),
        }
    )
