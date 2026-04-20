"""Intent Parser V2.

Multi-category, weighted signal matching. Each mode has signals organised into
three tiers (primary / secondary / vibe) and five semantic dimensions
(themes, terrain, mood, infrastructure, climate, travel_mode).

Design principles:
- Prefer lower confidence over false precision when signals are weak.
- Ambiguous prompts are flagged explicitly, not silently resolved.
- Every confidence score is accompanied by human-readable reasons.
- Vibe-like language (e.g. "dramatic", "forgotten") is captured but
  contributes only fractional weight so it cannot drive mode detection alone.
"""

import re
from app.core.logging import get_logger
from app.models.intent import ExperienceMode, PromptIntent

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Mode signal tiers
# Primary   → weight 3  (strong mode-specific language)
# Secondary → weight 1  (general supportive language)
# Vibe      → weight 0.5 (atmosphere words, low specificity)
# ---------------------------------------------------------------------------

_MODE_SIGNALS: dict[ExperienceMode, dict[str, list[str]]] = {
    ExperienceMode.SCENIC_ROADTRIP: {
        "primary": [
            "mountain pass", "horský průsmyk", "průsmyk",
            # Czech saddle/pass forms: nominative, genitive, plural
            "sedlo", "sedla", "sedlu", "sedel",
            "serpentine", "hairpin", "switchback", "scenic road",
            "alpine road", "pass road", "alpine drive", "high road",
            "výhledová silnice", "panoramic road", "cliff road",
            "gorge road", "canyon road", "ridge road",
        ],
        "secondary": [
            "výhled", "panorama", "pass", "road", "scenic",
            "mountain", "vista", "peak", "summit", "ridge",
            # Czech mountain-adj forms: horský / horská / horské
            "hory", "horský", "horská", "horské", "horskými",
            "silnice", "krajina", "viewpoint",
            "valley", "údolí", "cliff", "steza", "průjezd",
            "alpine", "alpský", "alpská", "mountain road", "drive",
            # Note: "col" removed — too short, false-positives on "collieries"
        ],
        "vibe": [
            "dramatic", "winding", "elevated", "sprawling", "steep",
            "drsný", "impozantní", "větrný", "exposed", "airy",
            "vertiginous", "breathtaking", "majestic",
        ],
    },
    ExperienceMode.REMOTE_LANDSCAPE: {
        "primary": [
            "wilderness", "remote", "isolated", "divočina", "samota",
            "bez lidí", "no people", "uninhabited", "no settlement",
            "no roads", "off-grid", "off grid", "backcountry",
            "odlehlá krajina", "pusté místo",
        ],
        "secondary": [
            "pustina", "poušť", "step", "tundra", "desert", "samotářský",
            "vzdálený", "odlehlý", "wild", "steppe", "plateau", "highland",
            "moorland", "expanse", "fjord", "moor", "heath", "fell",
            "taigas", "bog", "swamp", "badland", "prairie",
            "samota", "žádní turisté", "bare rock", "glacier",
        ],
        "vibe": [
            "lonely", "vast", "empty", "sparse", "desolate", "silent",
            "unpopulated", "barren", "minimal", "infinite", "endless",
            "osamělý", "prázdný", "tichý", "pustý", "nekonečný",
        ],
    },
    ExperienceMode.ABANDONED_INDUSTRIAL: {
        "primary": [
            # English forms — singular and plural
            "abandoned", "derelict", "brownfield", "disused",
            "industrial", "factory", "factories",
            "mine", "mines", "mining",
            # Czech forms — nominative + common declined/plural
            "opuštěný", "opuštěná", "opuštěné", "opuštěném", "opuštěných",
            "průmysl", "průmyslu", "průmyslový", "průmyslové",
            "továrna", "továrny", "továren",
            "důl", "doly", "dolu", "dolech",
            # Compound phrases
            "ruiny", "abandoned railway", "abandoned rail",
            "opuštěná továrna", "opuštěný důl", "průmyslové ruiny",
        ],
        "secondary": [
            "zbořeniny", "rezavý", "ruins", "ruin", "remnant",
            "coal", "steel", "uhlí", "ocel", "infrastructure",
            "rail", "silos", "shaft", "shafts", "chimney", "chimneys",
            "stack", "stacks", "ironworks",
            "colliery", "collieries", "blast furnace", "coking plant", "slag heap",
            "halda", "komín", "komíny", "koksovna", "šachta", "šachty",
            "rust belt", "post-industrial",
        ],
        "vibe": [
            "forgotten", "melancholic", "crumbling", "decaying", "rusty",
            "overgrown", "ghost", "dystopian",
            "melancholický", "zapomenutý", "rozpadlý", "zarůstající",
            "opuštěnost", "chátrání",
        ],
    },
}

_TERRAIN_KEYWORDS: dict[str, list[str]] = {
    "rocky": ["skála", "rocky", "rock", "kamenný", "bare rock", "scree", "talus"],
    "alpine": ["alpine", "alpský", "horský", "horská", "horské", "mountain", "subalpine", "above treeline"],
    "desert": ["poušť", "desert", "pustina", "suchý", "arid", "badland", "salt flat"],
    "flat": ["rovina", "flat", "plain", "nížina", "plateau", "tableland"],
    "coastal": ["pobřeží", "coast", "shore", "moře", "coastline", "cliffside", "seaside"],
    "volcanic": ["volcanic", "sopečný", "lava", "geothermal", "caldera", "crater"],
    "arctic": ["arctic", "tundra", "polar", "permafrost", "subarctic"],
    "wetland": ["swamp", "bog", "wetland", "marsh", "moor", "rašelina"],
}

_MOOD_KEYWORDS: dict[str, list[str]] = {
    "melancholic": [
        "melancholický", "smutný", "melancholic", "sad", "sombre", "bleak",
        "wistful", "elegiac", "melancholy",
    ],
    "vast": [
        "rozlehlý", "vast", "nekonečný", "wide", "expansive", "open", "sweeping",
    ],
    "raw": [
        "drsný", "drsná", "drsné", "raw", "harsh", "surový", "rugged",
        "unforgiving", "brutal", "stark",
    ],
    "lonely": [
        "samotářský", "lonely", "samota", "osamělý", "solitary", "lone",
        "isolated", "desolate",
    ],
    "dramatic": [
        "dramatic", "dramatický", "imposing", "striking", "breathtaking",
        "spectacular", "bold",
    ],
    "forgotten": [
        "forgotten", "zapomenutý", "lost", "ztracený", "abandoned", "neglected",
        "overlooked",
    ],
}

_INFRASTRUCTURE_KEYWORDS: dict[str, list[str]] = {
    "road": ["road", "silnice", "highway", "dálnice", "route"],
    "rail": ["rail", "railway", "železnice", "train", "vlak", "track"],
    "mine": ["mine", "důl", "shaft", "šachta", "colliery"],
    "industrial_plant": ["factory", "továrna", "plant", "works", "refinery"],
    "bridge": ["bridge", "most", "viaduct"],
    "pass": ["pass", "průsmyk", "sedlo", "col"],
}

_CLIMATE_KEYWORDS: dict[str, list[str]] = {
    "alpine": ["alpine", "snow", "sníh", "frost", "mráz", "glacier", "ledovec"],
    "arid": ["arid", "dry", "suchý", "drought", "desert heat"],
    "oceanic": ["rainy", "misty", "cloudy", "foggy", "mlha", "dešť"],
    "subarctic": ["cold", "freezing", "permafrost", "tundra", "arctic"],
}

_TRAVEL_MODE_KEYWORDS: dict[str, list[str]] = {
    "car": ["car", "auto", "drive", "driving", "road trip", "roadtrip", "jízda"],
    "hiking": ["hiking", "trek", "túra", "pěší", "walk", "foot"],
    "cycling": ["cycling", "bike", "bicycle", "kolo"],
    "train": ["train", "rail", "vlak", "železnice"],
}

_REGION_NAMES: list[str] = [
    # Countries — nominative + common Czech/Slovak declined forms
    "Polsko", "Polsku", "Polské", "Polska", "Poland",
    "Německo", "Německu", "Německé", "Germany",
    "Skandinávie", "Skandinávii", "Scandinavia",
    "Norsko", "Norsku", "Norské", "Norway",
    "Švédsko", "Švédsku", "Sweden",
    "Finsko", "Finsku", "Finland",
    "Rumunsko", "Rumunsku", "Romania",
    "Čechy", "Česko", "Česku", "Czech",
    "Slovensko", "Slovensku", "Slovakia",
    "Kazachstán", "Kazachstánu", "Kazakhstan",
    "Itálie", "Itálii", "Italy",
    "Španělsko", "Španělsku", "Spain",
    "Francie", "Francii", "France",
    "Island", "Islandu", "Islandě", "Iceland",
    "Skotsko", "Skotsku", "Scotland",
    "Irsko", "Irsku", "Ireland",
    "Chorvatsko", "Chorvatsku", "Croatia",
    "Slovinsko", "Slovinsku", "Slovenia",
    "Rakousko", "Rakousku", "Austria",
    "Švýcarsko", "Švýcarsku", "Switzerland",
    "Chile", "Argentina", "USA", "United States",
    "Arizona", "Utah", "Nevada", "New Mexico",
    # Mountain ranges and geographic regions — declined forms included
    "Alpy", "Alpách", "Alpami", "Alps",
    "Karpaty", "Karpatech", "Karpat", "Carpathians",
    "Beskydy", "Beskydech", "Šumava", "Šumavě",
    "Atacama", "Patagonie", "Patagonii", "Patagonia",
    "Hardangervidda", "Hardangerplošina",
    "Fjordy", "Fjordech", "Fjords",
    "Silesia", "Slezsko", "Slezsku", "Ruhr", "Ruhru",
    "Donbas", "Donbass", "Highlands", "Dolomites", "Dolomiti",
    # Norwegian adjective forms
    "norský", "norské", "norského", "norských", "norskými",
    # Southwestern US variant
    "Southwestern US", "Southwest US", "Southwestern United States",
    # Specific named places that indicate a region
    "Stelvio", "Transylvánie", "Transylvania", "Hardanger",
    "Geiranger", "Trollstigen", "Iceland Ring Road",
]

# ---------------------------------------------------------------------------
# Weights
# ---------------------------------------------------------------------------

_TIER_WEIGHTS = {"primary": 3.0, "secondary": 1.0, "vibe": 0.5}

# Above this raw score difference, the leading mode is unambiguous
_AMBIGUITY_THRESHOLD = 2.0

# Raw score normalisation cap — scores above this are all treated as 1.0
_NORMALISATION_CAP = 6.0


def _score_text(text: str, signals: dict[str, list[str]]) -> tuple[float, list[str]]:
    """Return (weighted_score, list_of_matched_phrases)."""
    text_lower = text.lower()
    total = 0.0
    matched: list[str] = []
    for tier, phrases in signals.items():
        weight = _TIER_WEIGHTS[tier]
        for phrase in phrases:
            if phrase.lower() in text_lower:
                total += weight
                matched.append(phrase)
    return total, matched


def _extract_list(text: str, keyword_map: dict[str, list[str]]) -> list[str]:
    text_lower = text.lower()
    return [
        category
        for category, keywords in keyword_map.items()
        if any(kw.lower() in text_lower for kw in keywords)
    ]


def parse_intent(prompt: str) -> PromptIntent:
    if not prompt or not prompt.strip():
        raise ValueError("Prompt nesmí být prázdný")

    text = prompt.strip()
    warnings: list[str] = []
    confidence_reasons: list[str] = []
    ambiguity_signals: list[str] = []

    # ── Mode detection ────────────────────────────────────────────────────
    raw_scores: dict[ExperienceMode, float] = {}
    matched_signals: dict[ExperienceMode, list[str]] = {}

    for mode, signals in _MODE_SIGNALS.items():
        score, matches = _score_text(text, signals)
        raw_scores[mode] = score
        matched_signals[mode] = matches

    max_score = max(raw_scores.values())

    if max_score == 0:
        raise ValueError(
            f"Prompt neodpovídá žádnému podporovanému módu. "
            f"Podporované módy: {', '.join(m.value for m in ExperienceMode)}"
        )

    sorted_modes = sorted(raw_scores.items(), key=lambda x: x[1], reverse=True)
    best_mode, best_raw = sorted_modes[0]
    second_mode, second_raw = sorted_modes[1]

    # Ambiguity check
    gap = best_raw - second_raw
    if second_raw > 0 and gap < _AMBIGUITY_THRESHOLD:
        ambiguity_signals.append(
            f"close_scores: {best_mode.value}={best_raw:.1f} vs "
            f"{second_mode.value}={second_raw:.1f} (gap={gap:.1f})"
        )
        warnings.append("ambiguous_mode")

    # Cross-mode vibe signals (e.g. "lonely" could signal remote but also abandoned)
    for mode, sigs in _MODE_SIGNALS.items():
        if mode == best_mode:
            continue
        _, vibe_matches = _score_text(text, {"vibe": sigs.get("vibe", [])})
        if vibe_matches:
            ambiguity_signals.append(
                f"vibe_crossover: {mode.value} vibe words present: {vibe_matches[:3]}"
            )

    # Confidence: normalise raw score to [0, 1], apply penalties
    confidence = min(1.0, best_raw / _NORMALISATION_CAP)

    word_count = len(text.split())
    if word_count < 4:
        warnings.append("too_vague")
        confidence = min(confidence, 0.35)
        confidence_reasons.append("prompt too short (<4 words) — confidence capped at 0.35")
    elif word_count < 7:
        warnings.append("too_vague")
        confidence = min(confidence, 0.50)
        confidence_reasons.append("short prompt (<7 words) — confidence capped at 0.50")

    if "ambiguous_mode" in warnings:
        confidence = min(confidence, 0.65)
        confidence_reasons.append(
            f"mode ambiguity between {best_mode.value} and {second_mode.value} — "
            f"confidence capped at 0.65"
        )

    if matched_signals[best_mode]:
        confidence_reasons.append(
            f"matched {len(matched_signals[best_mode])} signal(s) for "
            f"{best_mode.value}: {matched_signals[best_mode][:5]}"
        )
    else:
        confidence_reasons.append(f"no explicit signals for {best_mode.value} — inferred from weak context")

    # Round to 2 dp for readability
    confidence = round(confidence, 2)

    # ── Region extraction ─────────────────────────────────────────────────
    preferred_regions = [r for r in _REGION_NAMES if r.lower() in text.lower()]
    if not preferred_regions:
        warnings.append("no_region_detected")
        confidence_reasons.append("no region mentioned — pipeline will use registry-based fallback")

    # ── Semantic dimensions ───────────────────────────────────────────────
    terrain = _extract_list(text, _TERRAIN_KEYWORDS)
    mood = _extract_list(text, _MOOD_KEYWORDS)
    infrastructure = _extract_list(text, _INFRASTRUCTURE_KEYWORDS)
    climate = _extract_list(text, _CLIMATE_KEYWORDS)
    travel_mode_list = _extract_list(text, _TRAVEL_MODE_KEYWORDS)

    # ── Themes (mode → canonical OSM-relevant theme tags) ─────────────────
    themes = _mode_to_themes(best_mode)

    # ── Route style ───────────────────────────────────────────────────────
    route_style = "scattered"
    if re.search(r"\broadtrip\b|cesta z .* do |linear|route\b", text, re.IGNORECASE):
        route_style = "linear"
    elif re.search(r"\bokruh\b|\bloop\b|\bcircular\b", text, re.IGNORECASE):
        route_style = "loop"

    # ── Settlement density ────────────────────────────────────────────────
    settlement_density = "any"
    if re.search(
        r"žádní turisté|bez lidí|no people|wilderness|divočina|uninhabited|no settlement",
        text, re.IGNORECASE,
    ):
        settlement_density = "none"
    elif re.search(
        r"řídce osídlený|sparse|odlehlý|very few|hardly any",
        text, re.IGNORECASE,
    ):
        settlement_density = "sparse"

    intent = PromptIntent(
        original_prompt=prompt,
        mode=best_mode,
        themes=themes,
        terrain=terrain,
        mood=mood,
        infrastructure=infrastructure,
        climate=climate,
        travel_mode=travel_mode_list,
        preferred_regions=preferred_regions,
        excluded_regions=[],
        settlement_density=settlement_density,
        route_style=route_style,
        estimated_stops=5,
        confidence=confidence,
        parse_warnings=warnings,
        confidence_reasons=confidence_reasons,
        ambiguity_signals=ambiguity_signals,
    )

    logger.info(
        "intent_parsed",
        mode=intent.mode.value,
        confidence=intent.confidence,
        regions=intent.preferred_regions,
        warnings=intent.parse_warnings,
        ambiguity=intent.ambiguity_signals,
        confidence_reasons=intent.confidence_reasons,
    )
    return intent


def _mode_to_themes(mode: ExperienceMode) -> list[str]:
    return {
        ExperienceMode.ABANDONED_INDUSTRIAL: [
            "abandoned_industrial", "industrial_heritage", "ruins",
        ],
        ExperienceMode.SCENIC_ROADTRIP: [
            "mountain_pass", "panoramic_view", "scenic_road",
        ],
        ExperienceMode.REMOTE_LANDSCAPE: [
            "isolation", "wilderness", "remote_nature",
        ],
    }[mode]
