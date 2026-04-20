# Prompt Parsing a PromptIntent — V2

## Přehled

Prompt parsing je první krok pipeline. Převede volný text od uživatele na strukturovaný `PromptIntent` — datový model, který všechny další kroky pipeline konzumují.

Parser je deterministický (weighted keyword matching + rule-based), ne LLM-based. To umožňuje přesné debugging a ladění relevance bez externích závislostí.

**V2 změny oproti V1:**
- Signály jsou organizovány do tří vah: primary (3.0), secondary (1.0), vibe (0.5)
- Každý mód má bohatší sadu synonym a variant formulací (EN + CZ declined forms)
- Přidány kategorie: `infrastructure`, `climate`, `travel_mode`
- Výstup obsahuje `confidence_reasons` a `ambiguity_signals` pro debugging
- Nejistota se projevuje nižší confidence, ne falešnou přesností
- Kombinované prompty ("lonely alpine villages with dramatic mountain roads") jsou lépe zpracovány díky vícevrstvým signálům

---

## Podporované módy

| Mód | Primary signály (weight 3) | Secondary signály (weight 1) | Typický prompt |
|---|---|---|---|
| `scenic_roadtrip` | mountain pass, serpentine, hairpin, switchback, sedlo, průsmyk | viewpoint, panorama, alpine, ridge, pass, road | „drsná horská sedla s panoramatickým výhledem" |
| `remote_landscape` | wilderness, remote, isolated, bez lidí, divočina, uninhabited | desert, fell, heath, moor, steppe, plateau | „vzdálené plošiny bez lidí v Norsku" |
| `abandoned_industrial` | abandoned, industrial, factory, mine, derelict, opuštěné | ruins, shaft, colliery, slag heap, brownfield | „opuštěné průmyslové lokality s důlní infrastrukturou" |

Vibe signály (weight 0.5) zachytávají atmosféru: „dramatic", „forgotten", „lonely", „vast". Samy o sobě nestačí pro detekci módu.

---

## PromptIntent model

```python
class PromptIntent(BaseModel):
    original_prompt: str
    mode: ExperienceMode

    # Sémantické kategorie
    themes: list[str]              # ["mountain_pass", "panoramic_view", "scenic_road"]
    terrain: list[str]             # ["rocky", "alpine", "volcanic"]
    mood: list[str]                # ["melancholic", "vast", "raw", "lonely", "dramatic"]
    infrastructure: list[str]      # ["road", "rail", "mine", "pass"]
    climate: list[str]             # ["alpine", "arid", "oceanic", "subarctic"]
    travel_mode: list[str]         # ["car", "hiking", "cycling", "train"]

    # Geografické preference
    preferred_regions: list[str]   # ["Polsku", "Alps", "Scandinavia"]
    excluded_regions: list[str]

    # Charakter míst
    settlement_density: str        # "none" | "sparse" | "any"

    # Charakter trasy
    route_style: str               # "linear" | "loop" | "scattered"
    estimated_stops: int

    # Parser metadata — pro debugging
    confidence: float              # 0.0–1.0
    parse_warnings: list[str]      # ["ambiguous_mode", "no_region_detected", "too_vague"]
    confidence_reasons: list[str]  # Vysvětlení proč je confidence tohoto levelu
    ambiguity_signals: list[str]   # Konkrétní signály ambiguity, pokud existují
```

---

## Jak parser pracuje (V2)

### Krok 1: Detekce módu (weighted signal scoring)

Pro každý mód se text prohledá přes tři vrstvy signálů:

```
primary tier (weight 3.0):  silné, mód-specifické signály
secondary tier (weight 1.0): obecné podpůrné signály
vibe tier (weight 0.5):      atmosférická slova, nízká specificita
```

Skóre = součet vah všech matchujících signálů. Mód s nejvyšším skóre vyhráje.

**Ambiguity detection:** Pokud je rozdíl mezi prvním a druhým módem < 2.0, přidá se `ambiguous_mode` do `parse_warnings` a `confidence` je zastropována na 0.65.

### Krok 2: Extrakce regionu

Parser hledá v promptu zmínky geografických názvů ze seznamu `_REGION_NAMES`, který pokrývá:
- Státy (CZ/SK + anglicky + časté skloňované formy: „Polsku", „Norsku", „Alpami")
- Pohoří (Alpy, Karpaty, Highlands, Dolomites)
- Specifická místa (Stelvio, Hardangervidda, Patagonia)
- Adjektivní formy (norský, norské, norských)

Pokud region nenajde → `no_region_detected` v `parse_warnings` a Region Discovery použije registry fallback.

### Krok 3: Extrakce sémantických kategorií

Rule-based mapping z klíčových slov (CZ + EN):
- `terrain`: rocky, alpine/horský/horská, desert/poušť, coastal, volcanic, arctic, wetland
- `mood`: melancholic, vast, raw/drsný/drsná, lonely, dramatic, forgotten
- `infrastructure`: road, rail/railway, mine, industrial_plant, bridge, pass
- `climate`: alpine (sníh/frost), arid, oceanic (mlha/déšť), subarctic
- `travel_mode`: car, hiking, cycling, train

### Krok 4: Route style a settlement density

- `route_style`: `linear` (roadtrip, „z A do B"), `loop` (okruh), `scattered` (default)
- `settlement_density`: `none` (bez lidí/uninhabited), `sparse` (odlehlý/very few), `any`

### Krok 5: Confidence výpočet

```
raw_score = suma vah matchujících signálů pro vítězný mód
confidence = min(1.0, raw_score / 6.0)  # normalizace

Penalizace:
  < 4 slova v promptu  → confidence ≤ 0.35, "too_vague"
  < 7 slov             → confidence ≤ 0.50, "too_vague"
  ambiguous_mode       → confidence ≤ 0.65
```

---

## Příklady parsování (V2)

### Příklad 1 — silný abandoned industrial

**Prompt:** `opuštěné průmyslové oblasti s historií těžby uhlí v Polsku`

```json
{
  "mode": "abandoned_industrial",
  "themes": ["abandoned_industrial", "industrial_heritage", "ruins"],
  "terrain": [],
  "mood": [],
  "infrastructure": ["mine"],
  "preferred_regions": ["Polsku"],
  "settlement_density": "any",
  "confidence": 0.67,
  "confidence_reasons": ["matched 2 primary signals: ['průmysl', 'uhlí']"],
  "parse_warnings": [],
  "ambiguity_signals": []
}
```

### Příklad 2 — silný scenic roadtrip s regionem

**Prompt:** `drsná horská sedla s panoramatickým výhledem nad Alpami`

```json
{
  "mode": "scenic_roadtrip",
  "themes": ["mountain_pass", "panoramic_view", "scenic_road"],
  "terrain": ["alpine"],
  "mood": ["raw"],
  "preferred_regions": ["Alpami"],
  "confidence": 1.0,
  "confidence_reasons": ["matched 4 signals: ['sedla', 'výhled', 'panorama', 'horská']"],
  "parse_warnings": [],
  "ambiguity_signals": []
}
```

### Příklad 3 — kombinovaný prompt (ambiguous)

**Prompt:** `dramatic pass road with derelict infrastructure`

```json
{
  "mode": "scenic_roadtrip",
  "themes": ["mountain_pass", "panoramic_view", "scenic_road"],
  "mood": ["dramatic"],
  "confidence": 0.65,
  "confidence_reasons": [
    "mode ambiguity between scenic_roadtrip and abandoned_industrial — capped at 0.65"
  ],
  "parse_warnings": ["ambiguous_mode", "no_region_detected"],
  "ambiguity_signals": [
    "close_scores: scenic_roadtrip=5.5 vs abandoned_industrial=4.0 (gap=1.5)"
  ]
}
```

### Příklad 4 — vague prompt

**Prompt:** `výlet`

```json
{
  "confidence": 0.35,
  "parse_warnings": ["too_vague", "no_region_detected"],
  "confidence_reasons": ["prompt too short (<4 words) — confidence capped at 0.35"]
}
```

---

## Debuggovatelnost výstupu

Každý `PromptIntent` nese `confidence_reasons` — seznam lidsky čitelných důvodů pro danou confidence hodnotu. Při slabém výsledku pipeline je z těchto reasons hned jasné, co parser "viděl" a "neviděl".

Příklady `confidence_reasons`:
```
"matched 4 signal(s) for scenic_roadtrip: ['sedla', 'výhled', 'panorama', 'horská']"
"mode ambiguity between scenic_roadtrip and abandoned_industrial — confidence capped at 0.65"
"no region mentioned — pipeline will use registry-based fallback"
"prompt too short (<4 words) — confidence capped at 0.35"
```

---

## Co parser nedělá (první iterace)

- Nevolá LLM (žádné API v parseru)
- Neřeší kontradiktorní požadavky (jen zaznamená do `parse_warnings`)
- Nepoužívá NLP lemmatizaci — přidány ruční declined forms pro CZ
- Nedetekuje negace ("nechci opuštěné továrny")
