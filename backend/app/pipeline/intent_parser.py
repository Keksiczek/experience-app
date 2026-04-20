import re
from app.core.logging import get_logger
from app.models.intent import ExperienceMode, PromptIntent

logger = get_logger(__name__)

_MODE_KEYWORDS: dict[ExperienceMode, list[str]] = {
    ExperienceMode.SCENIC_ROADTRIP: [
        "výhled", "panorama", "sedlo", "průsmyk", "silnice", "krajina",
        "hory", "horský", "viewpoint", "pass", "road", "scenic", "mountain",
        "vista", "peak", "summit", "ridge", "col",
    ],
    ExperienceMode.REMOTE_LANDSCAPE: [
        "samota", "divočina", "pustina", "poušť", "step", "tundra",
        "wilderness", "remote", "desert", "no people", "isolated", "samotářský",
        "vzdálený", "odlehlý", "bez lidí", "wild",
    ],
    ExperienceMode.ABANDONED_INDUSTRIAL: [
        "opuštěný", "průmysl", "továrna", "důl", "ruiny", "zbořeniny",
        "abandoned", "industrial", "factory", "mine", "ruins", "derelict",
        "rezavý", "opuštěná", "průmyslový", "brownfield",
    ],
}

_TERRAIN_KEYWORDS: dict[str, list[str]] = {
    "rocky": ["skála", "rocky", "rock", "kamenný"],
    "alpine": ["alpine", "alpský", "horský", "mountain"],
    "desert": ["poušť", "desert", "pustina", "suchý"],
    "flat": ["rovina", "flat", "plain", "nížina"],
    "coastal": ["pobřeží", "coast", "shore", "moře"],
}

_MOOD_KEYWORDS: dict[str, list[str]] = {
    "melancholic": ["melancholický", "smutný", "opuštěný", "melancholic"],
    "vast": ["rozlehlý", "vast", "nekonečný", "wide"],
    "raw": ["drsný", "raw", "harsh", "surový"],
    "lonely": ["samotářský", "lonely", "samota", "osamělý"],
}

_REGION_NAMES: list[str] = [
    "Polsko", "Poland", "Německo", "Germany", "Skandinávie", "Scandinavia",
    "Norsko", "Norway", "Švédsko", "Sweden", "Finsko", "Finland",
    "Rumunsko", "Romania", "Čechy", "Česko", "Czech", "Slovensko", "Slovakia",
    "Alpy", "Alps", "Karpaty", "Carpathians", "Beskydy", "Šumava",
    "Kazachstán", "Kazakhstan", "Atacama", "Patagonie", "Patagonia",
    "Itálie", "Italy", "Španělsko", "Spain", "Francie", "France",
]


def _match_keywords(text: str, keywords: list[str]) -> int:
    text_lower = text.lower()
    return sum(1 for kw in keywords if kw.lower() in text_lower)


def parse_intent(prompt: str) -> PromptIntent:
    if not prompt or not prompt.strip():
        raise ValueError("Prompt nesmí být prázdný")

    text = prompt.strip()
    warnings: list[str] = []

    # Mode detection
    scores: dict[ExperienceMode, int] = {
        mode: _match_keywords(text, kws)
        for mode, kws in _MODE_KEYWORDS.items()
    }
    max_score = max(scores.values())

    if max_score == 0:
        raise ValueError(
            f"Prompt neodpovídá žádnému podporovanému módu. "
            f"Podporované módy: {', '.join(m.value for m in ExperienceMode)}"
        )

    sorted_modes = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    best_mode, best_score = sorted_modes[0]
    second_score = sorted_modes[1][1] if len(sorted_modes) > 1 else 0

    if best_score - second_score <= 1 and second_score > 0:
        warnings.append("ambiguous_mode")

    confidence = min(1.0, best_score / 4.0)
    if len(text.split()) < 5:
        warnings.append("too_vague")
        confidence = min(confidence, 0.4)

    # Region extraction
    preferred_regions = [r for r in _REGION_NAMES if r.lower() in text.lower()]
    if not preferred_regions:
        warnings.append("no_region_detected")

    # Terrain extraction
    terrain = [t for t, kws in _TERRAIN_KEYWORDS.items() if _match_keywords(text, kws) > 0]

    # Mood extraction
    mood = [m for m, kws in _MOOD_KEYWORDS.items() if _match_keywords(text, kws) > 0]

    # Themes = mode-specific tags
    themes = _mode_to_themes(best_mode)

    # Route style
    route_style = "scattered"
    if re.search(r"\broadtrip\b|cesta z .* do |linear", text, re.IGNORECASE):
        route_style = "linear"
    elif re.search(r"\bokruh\b|\bloop\b|\bcircular\b", text, re.IGNORECASE):
        route_style = "loop"

    # Settlement density
    settlement_density = "any"
    if re.search(r"žádní turisté|bez lidí|no people|wilderness|divočina", text, re.IGNORECASE):
        settlement_density = "none"
    elif re.search(r"řídce osídlený|sparse|odlehlý", text, re.IGNORECASE):
        settlement_density = "sparse"

    intent = PromptIntent(
        original_prompt=prompt,
        mode=best_mode,
        themes=themes,
        terrain=terrain,
        mood=mood,
        preferred_regions=preferred_regions,
        excluded_regions=[],
        settlement_density=settlement_density,
        infrastructure=[],
        climate=[],
        route_style=route_style,
        estimated_stops=5,
        confidence=confidence,
        parse_warnings=warnings,
    )

    logger.info(
        "intent_parsed",
        mode=intent.mode,
        confidence=intent.confidence,
        regions=intent.preferred_regions,
        warnings=intent.parse_warnings,
    )
    return intent


def _mode_to_themes(mode: ExperienceMode) -> list[str]:
    return {
        ExperienceMode.ABANDONED_INDUSTRIAL: [
            "abandoned_industrial", "industrial_heritage", "ruins"
        ],
        ExperienceMode.SCENIC_ROADTRIP: [
            "mountain_pass", "panoramic_view", "scenic_road"
        ],
        ExperienceMode.REMOTE_LANDSCAPE: [
            "isolation", "wilderness", "remote_nature"
        ],
    }[mode]
