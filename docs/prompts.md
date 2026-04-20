# Prompt Parsing a PromptIntent

## Přehled

Prompt parsing je první krok pipeline. Převede volný text od uživatele na strukturovaný `PromptIntent` — datový model, který všechny další kroky pipeline konzumují.

V první iteraci je parser deterministický (keyword matching + rule-based), ne LLM-based. To zjednodušuje debugging a ladění relevance.

---

## Podporované módy (první iterace)

Pipeline v první iteraci podporuje 3 pevné módy. Mód je odvozený z promptu automaticky.

| Mód | Klíčová slova a témata | Typický prompt |
|---|---|---|
| `scenic_roadtrip` | výhled, panorama, silnice, sedlo, průsmyk, kraj, příroda, krajina | „drsná horská sedla s výhledem" |
| `remote_landscape` | pustina, divočina, samota, vzdálený, bez lidí, step, poušť, tundra | „samotářský roadtrip, žádní turisté" |
| `abandoned_industrial` | opuštěný, průmysl, továrna, důl, ruiny, zbořeniny, rezavý | „opuštěné průmyslové oblasti" |

Pokud prompt neodpovídá jednoznačně jednomu módu, pipeline vrátí `400 Ambiguous prompt` s nápovědou.

---

## PromptIntent model

```python
class ExperienceMode(str, Enum):
    SCENIC_ROADTRIP = "scenic_roadtrip"
    REMOTE_LANDSCAPE = "remote_landscape"
    ABANDONED_INDUSTRIAL = "abandoned_industrial"

class PromptIntent(BaseModel):
    original_prompt: str
    mode: ExperienceMode

    # Sémantické kategorie
    themes: list[str]          # ["mountain_pass", "isolation", "panoramic_view"]
    terrain: list[str]         # ["rocky", "alpine", "desert"]
    mood: list[str]            # ["melancholic", "vast", "raw"]

    # Geografické preference
    preferred_regions: list[str]   # ["Poland", "Scandinavia"] nebo []
    excluded_regions: list[str]    # ["Alps tourist areas"] nebo []

    # Charakter míst
    settlement_density: str    # "none" | "sparse" | "any"
    infrastructure: list[str]  # ["dirt_road", "no_paved"] nebo []
    climate: list[str]         # ["harsh", "continental"] nebo []

    # Charakter trasy
    route_style: str           # "linear" | "loop" | "scattered"
    estimated_stops: int       # 4–8, odvozeno z délky a komplexity promptu

    # Metadata parsingu
    confidence: float          # 0.0–1.0, jak jistý si parser je interpretací
    parse_warnings: list[str]  # např. ["region_too_vague", "conflicting_themes"]
```

---

## Jak parser pracuje

### Krok 1: Detekce módu

Parser prochází prompt přes sadu keyword sad per mód. Každý match zvyšuje skóre pro daný mód.

```python
MODE_KEYWORDS = {
    ExperienceMode.SCENIC_ROADTRIP: [
        "výhled", "panorama", "sedlo", "průsmyk", "silnice", "krajina",
        "viewpoint", "pass", "road", "scenic", "mountain", "vista"
    ],
    ExperienceMode.REMOTE_LANDSCAPE: [
        "samota", "divočina", "pustina", "poušť", "step", "tundra",
        "wilderness", "remote", "desert", "no people", "isolated"
    ],
    ExperienceMode.ABANDONED_INDUSTRIAL: [
        "opuštěný", "průmysl", "továrna", "důl", "ruiny", "zbořeniny",
        "abandoned", "industrial", "factory", "mine", "ruins", "derelict"
    ],
}
```

Mód s nejvyšším skóre vyhráje. Pokud jsou dva módy do 2 bodů od sebe → `parse_warnings += ["ambiguous_mode"]`.

### Krok 2: Extrakce regionu

Parser hledá v promptu zmínky o státech, pohořích, oblastech. Používá statický seznam z `data/samples/regions.json`. Pokud region nenajde, `preferred_regions = []` a Region Discovery použije heuristiky z módu.

### Krok 3: Extrakce themes, terrain, mood

Rule-based mapping z klíčových slov na standardizované hodnoty. Themes jsou pak použity v scoringu pro `prompt_relevance`.

### Krok 4: Odvození route_style a estimated_stops

- Kratší prompt bez zmínky trasy → `scattered`
- Zmínka „roadtrip", „cesta z A do B" → `linear`
- Zmínka „okruh", „loop" → `loop`
- `estimated_stops` = 5 (default), +1 per zmínka konkrétního typu místa, max 8

---

## Příklady parsování

### Příklad 1

**Prompt:** `opuštěné průmyslové oblasti s historií těžby uhlí v Polsku`

```json
{
  "mode": "abandoned_industrial",
  "themes": ["abandoned_industrial", "coal_mining", "industrial_heritage"],
  "terrain": ["flat", "lowland"],
  "mood": ["melancholic", "raw"],
  "preferred_regions": ["Poland"],
  "settlement_density": "sparse",
  "route_style": "scattered",
  "estimated_stops": 5,
  "confidence": 0.92
}
```

### Příklad 2

**Prompt:** `drsná horská sedla ve Skandinávii, žádní turisté, jen sníh a vítr`

```json
{
  "mode": "remote_landscape",
  "themes": ["mountain_pass", "isolation", "harsh_climate"],
  "terrain": ["alpine", "rocky", "snowy"],
  "mood": ["vast", "raw", "lonely"],
  "preferred_regions": ["Scandinavia"],
  "settlement_density": "none",
  "infrastructure": ["no_paved"],
  "climate": ["harsh", "subarctic"],
  "route_style": "scattered",
  "estimated_stops": 5,
  "confidence": 0.85
}
```

### Příklad 3 — ambiguous

**Prompt:** `výlet do hor`

```json
{
  "mode": "scenic_roadtrip",
  "themes": ["mountain"],
  "terrain": [],
  "mood": [],
  "preferred_regions": [],
  "confidence": 0.45,
  "parse_warnings": ["too_vague", "no_region_detected"]
}
```

→ Pipeline pokračuje, ale s nízkou confidence — výsledek bude označen jako `low_confidence_intent`.

---

## Co parser nedělá (první iterace)

- Nevolá LLM (žádné GPT, žádné Claude API v parseru)
- Neinterpretuje metafory nebo poetický jazyk (jen keyword matching)
- Nepodporuje multi-language normalizaci (češtinu a angličtinu zpracovává nezávisle)
- Neřeší kontradiktorní požadavky (jen je zaznamená do `parse_warnings`)

---

## Budoucí iterace

- LLM-assisted parsing pro poetické nebo vágní prompty
- Structured output z Claude API pro spolehlivou extrakci
- Feedback loop: zaznamenávat, které parse_warnings vedou k špatné experience
