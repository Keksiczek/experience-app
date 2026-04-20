# Technická architektura

## Přehled

Aplikace je postavená jako lineární pipeline s explicitními quality gates mezi kroky. Každý krok pipeline je samostatný modul s jasně definovaným vstupem, výstupem a sadou failure modes.

Backend je FastAPI aplikace. Zpracování experience je asynchronní job — výsledek není vrácen synchronně, ale je uložen a dostupný přes GET endpoint.

## Pipeline

```
Prompt (string)
    │
    ▼
[1] Intent Parser V2
    │  → PromptIntent (themes, terrain, mood, infrastructure, climate,
    │                   travel_mode, route_style, mode, confidence_reasons,
    │                   ambiguity_signals, parse_warnings)
    │  ✗ FAIL: prompt nesrozumitelný nebo mimo podporované módy → 400
    │
    ▼
[2] Region Discovery V2
    │  → RegionCandidate[] (bbox, name, source, decision_reasons,
    │                        expected_media_coverage, known_limitations)
    │  Priorita: Nominatim → registry (mode-aware) → static JSON fallback
    │  ✗ FAIL: žádný region nenalezen → pipeline se zastaví
    │  ⚠ WARN: known_limitations propagovány do metadata.warnings
    │
    ▼
[3] Place Discovery V2
    │  → PlaceCandidate[] (lat, lon, tags, signal_strength, discovery_warnings)
    │  OSM queries: tiered presets (must_have / strong / weak / blacklist)
    │  Výstup: (places, discovery_warnings[])
    │  ✗ FAIL: méně než MIN_PLACES míst → pipeline se zastaví
    │  ⚠ WARN: < IDEAL_PLACES, žádné must_have hits, vysoký podíl no_name_tag
    │
    ▼
[4] Media Resolution
    │  → MediaCandidate[] (provider, url, license, coverage_score)
    │  ✗ FAIL: nikdy nezastaví pipeline
    │  ⚠ WARN: chybí média → fallback_level se zvýší
    │
    ▼
[5] Experience Composer V2
    │  → ExperienceStop[] (ordered, scored, decision_reasons[], fallback_reason)
    │  Scoring: prompt_relevance + media_availability + scenic_value +
    │            diversity_bonus + context_richness + similarity_penalty + combo_bonus
    │
    ▼
[6] Narrator
    │  → narration pro každý stop, summary pro celou experience
    │  Pravidlo: narrace smí obsahovat jen fakta z dat předchozích kroků
    │
    ▼
Experience (výsledný objekt)
    └── generation_metadata.warnings[]          — agregovaná varování z celé pipeline
    └── generation_metadata.decision_reasons[]  — klíčová rozhodnutí pipeline
    └── generation_metadata.degradation_reason  — pokud pipeline degradovala
    └── stops[].decision_reasons[]              — per-stop scoring reasons
    └── stops[].fallback_reason                 — proč stop nemá média
```

## Quality Gates a degradační logika

Každý gate má přesný threshold (konfigurabilní v `core/config.py`) a definované chování při překročení.

### Tvrdé gates — pipeline se zastaví

| Gate | Config klíč | Default | Akce při selhání |
|---|---|---|---|
| `intent_valid` | — | — | `400 Bad Request`, pipeline se nespustí |
| `region_found` | — | — | `job_status = failed`, `error_code = no_region_found` |
| `min_places` | `PIPELINE_MIN_PLACES` | 3 | `job_status = failed`, `error_code = too_few_places` |
| `min_stops` | `PIPELINE_STOPS_MIN` | 3 | `job_status = failed`, `error_code = composer_no_stops` |

### Měkké gates — pipeline pokračuje s degradací

| Gate | Config klíč | Default | Při překročení |
|---|---|---|---|
| `ideal_places` | `PIPELINE_IDEAL_PLACES` | 8 | `estimated_stops` se sníží na `len(places) - 1` (zkrácená experience) |
| `score_threshold` | `PIPELINE_SCORE_THRESHOLD` | 0.40 | Normální threshold pro zařazení stopu |
| `score_threshold_emergency` | `PIPELINE_SCORE_THRESHOLD_EMERGENCY` | 0.25 | Použito když žádný stop nedosáhne normálního prahu → `quality_flag = emergency_threshold` |
| `media_low` | `PIPELINE_MEDIA_LOW_THRESHOLD` | 0.50 | Pokud > 50 % stops nemá média → `quality_flag = low_media` |
| `narration_weak` | `PIPELINE_NARRATION_WEAK_THRESHOLD` | 0.50 | `narration_confidence < 0.50` na majoritě stops → `quality_flag = partial_narration` |
| `narration_min_tags` | `PIPELINE_NARRATION_MIN_TAGS` | 2 | Méně než 2 smysluplné tagy → krátká faktická poznámka místo šablony |

### Degradační cesty — vizualizace

```
places >= 8 (ideal)
    → target = PIPELINE_STOPS_TARGET (6)
    → normální experience

3 <= places < 8 (suboptimal)
    → target = max(MIN_STOPS, places - 1)
    → quality_flag = "few_places"
    → experience bude kratší, ale platná

places < 3
    → ABORT

scoring threshold:
    → normální: >= 0.40 → stop zařazen
    → emergency: 0.25–0.40 → stop zařazen + quality_flag = "emergency_threshold"
    → pod 0.25 → stop zamítnut

narration context:
    → confidence >= 0.75  → full narration (tags + wikidata + name)
    → 0.50–0.75           → partial narration (tags + name)
    → 0.25–0.50           → short factual note only ("OSM záznam: key=val.")
    → < 0.25              → bare note ("Lokalita na souřadnicích X. Bez dat.")
```

## Pipeline Explainability

Každý pipeline krok přispívá do `GenerationMetadata`, která je součástí finálního `Experience` objektu:

```python
class GenerationMetadata(BaseModel):
    pipeline_steps: list[str]       # kroky, které proběhly
    warnings: list[str]             # agregovaná varování ze všech kroků
    decision_reasons: list[str]     # klíčová rozhodnutí (region selection, scoring)
    degradation_reason: str | None  # hlavní důvod degradace, pokud nastala
```

Každý `ExperienceStop` nese:
```python
decision_reasons: list[str]   # scoring breakdown v lidsky čitelné formě
fallback_reason: str | None   # proč stop nemá média nebo má low context
```

Cíl: u slabého výsledku musí být z těchto polí dohledatelné, ve kterém kroku pipeline nastalo selhání nebo degradace (intent / region / discovery / scoring / media / narration).

## Scoring V2

Bodové schéma rozšířeno o nové komponenty:

| Komponenta | Popis | Rozsah |
|---|---|---|
| `prompt_relevance` | % témat z intent matchujících OSM tagy | 0.1–1.0 |
| `media_availability` | Mapillary/Wikimedia pokrytí | 0.0–1.0 |
| `scenic_value` | Atmosférická hodnota místa (tagy) | 0.0–1.0 |
| `diversity_bonus` | Prostorová diverzita vs. vybraných stops | 0.0–1.0 |
| `route_coherence` | Neutrální 0.5 (routing dosud neimplementován) | 0.5 |
| `context_richness` | Počet smysluplných OSM tagů (normalizováno na 8) | 0.0–1.0 |
| `similarity_penalty` | Srážka za podobný tag profil jako existující stop | 0.0–0.2 |
| `combo_bonus` | Bonus: dobrá relevance + médium + kontext zároveň | 0.0–0.08 |

`context_richness` ovlivňuje výsledné skóre jako soft modifier ±10%. `similarity_penalty` snižuje skóre pro příliš podobné kandidáty bez ohledu na vzdálenost.

## OSM Query Presets (Place Discovery V2)

Místo jednoho plochého seznamu filtrů má každý mód vícevrstvý preset:

```python
class ModePreset:
    must_have: list[str]   # silné, mód-definující signály
    strong: list[str]      # dobré kandidáty — jasně relevantní
    weak: list[str]        # doplňkové / kontextuální kandidáty
    blacklist: dict[str, list[str]]  # tagy = hluk pro tento mód
```

Každý vrácený `PlaceCandidate` nese `signal_strength` ("must_have" / "strong" / "weak") a `discovery_warnings` (chybějící name tag, řídké tagy).

### Job persistence

Výchozí implementace je `SQLiteJobStore` (`app/jobs/sqlite_job_store.py`). Jobs přežívají restart procesu a jsou dostupné přes `GET /experiences/{id}`. TTL evikce (default: 7 dní) odstraňuje staré záznamy při každém `save()`.

V mock mode (`MOCK_MODE=true`) se používá `InMemoryJobStore` — žádné DB soubory.

Konfigurace:
- `JOB_STORE_PATH` — cesta k SQLite souboru (default: `./data/jobs.db`)
- `JOB_STORE_TTL_DAYS` — TTL v dnech (default: 7)

### Mock mode

Celá pipeline lze spustit bez live API nastavením `MOCK_MODE=true`. V tom případě:
- `MockNominatimProvider` vrátí bbox pro Horní Slezsko z `data/samples/nominatim_silesia.json`
- `MockOverpassProvider` vrátí abandonované průmyslové lokality z `data/samples/overpass_silesia_abandoned.json`
- `MockMapillaryProvider` a `MockWikimediaProvider` vrátí statické odpovědi ze sample souborů

Viz `app/core/mock_mode.py`.

## Datový tok a modely

```
PromptIntent
    └── použit v: RegionDiscovery, PlaceDiscovery (scoring)

RegionCandidate[]
    └── použit v: PlaceDiscovery (bbox pro Overpass query)

PlaceCandidate[]
    └── použit v: MediaResolution, ExperienceComposer

MediaCandidate[]
    └── použit v: ExperienceComposer (přiřazení k stop)

ExperienceStop[]
    └── použit v: Narrator, Experience

Experience
    └── výsledný objekt vrácený přes API
```

## Adresářová struktura backendu

```
backend/
├── pyproject.toml
├── app/
│   ├── main.py                  # FastAPI app, lifespan
│   ├── api/
│   │   └── routes/
│   │       ├── experience.py    # POST /experiences, GET /experiences/{id}
│   │       └── health.py        # GET /health
│   ├── core/
│   │   ├── config.py            # Settings (pydantic-settings)
│   │   └── logging.py           # Structured logging setup
│   ├── models/
│   │   ├── intent.py            # PromptIntent, ExperienceMode
│   │   ├── place.py             # PlaceCandidate, RegionCandidate
│   │   ├── media.py             # MediaCandidate, MediaProvider
│   │   └── experience.py        # ExperienceStop, Experience
│   ├── pipeline/
│   │   ├── intent_parser.py     # Prompt → PromptIntent
│   │   ├── region_discovery.py  # PromptIntent → RegionCandidate[]
│   │   ├── place_discovery.py   # RegionCandidate[] → PlaceCandidate[]
│   │   ├── media_resolution.py  # PlaceCandidate[] → MediaCandidate[]
│   │   ├── experience_composer.py # → ExperienceStop[]
│   │   └── narrator.py          # → narration strings
│   ├── providers/
│   │   ├── base.py              # BaseProvider ABC
│   │   ├── osm.py               # Overpass API adapter
│   │   ├── mapillary.py         # Mapillary API adapter
│   │   ├── wikidata.py          # Wikidata SPARQL adapter
│   │   ├── wikimedia.py         # Wikimedia Commons geosearch adapter
│   │   └── nominatim.py         # Nominatim geocoding adapter
│   ├── cache/
│   │   ├── base.py              # BaseCache ABC
│   │   └── file_cache.py        # File-based cache (JSON, gzip)
│   ├── scoring/
│   │   └── scorer.py            # Heuristický scoring engine
│   └── jobs/
│       └── experience_job.py    # Background job orchestrator
```

## API endpoints (první iterace)

```
GET /experiences?limit=20
    Response: [{ "job_id": string }, ...]
    Vrátí seznam posledních job ID (newest first). Limit max 100.

POST /experiences
    Body: { "prompt": string }
    Response: { "job_id": string, "status": "pending" }

GET /experiences/{job_id}
    Response: Experience | { "status": "pending"|"failed", "error": string }

GET /health
    Response: { "status": "ok", "providers": { ... } }
```

## Cache strategie

Každý provider call je cachován s klíčem odvozeným z parametrů requestu. Cache je file-based v první iteraci, ale skrze `BaseCache` ABC snadno nahraditelná Redisem.

TTL per provider:
- Nominatim: 7 dní (geocoding se nemění)
- Overpass: 24 hodin (OSM data jsou stabilní)
- Wikidata: 48 hodin
- Wikimedia: 24 hodin
- Mapillary: 6 hodin (coverage se mění)

## Logování

Každý pipeline krok loguje:
- vstup (zkrácená forma)
- výstup (počet výsledků, skóre)
- trvání
- zda byl výsledek z cache nebo živý

Formát: structured JSON (za použití `structlog`).

## Konfigurace

Vše přes environment variables, defaulty v `core/config.py`. Kompletní soupis:

```
# API keys
MAPILLARY_API_KEY

# Cache
CACHE_DIR
CACHE_TTL_NOMINATIM   (default: 604800 = 7 dní)
CACHE_TTL_OVERPASS    (default: 86400  = 24 h)
CACHE_TTL_WIKIDATA    (default: 172800 = 48 h)
CACHE_TTL_WIKIMEDIA   (default: 86400  = 24 h)
CACHE_TTL_MAPILLARY   (default: 21600  = 6 h)

# Quality gates
PIPELINE_MIN_PLACES                  (default: 3)
PIPELINE_IDEAL_PLACES                (default: 8)
PIPELINE_STOPS_TARGET                (default: 6)
PIPELINE_STOPS_MIN                   (default: 3)
PIPELINE_SCORE_THRESHOLD             (default: 0.40)
PIPELINE_SCORE_THRESHOLD_EMERGENCY   (default: 0.25)
PIPELINE_MEDIA_LOW_THRESHOLD         (default: 0.50)
PIPELINE_NARRATION_MIN_TAGS          (default: 2)
PIPELINE_NARRATION_WEAK_THRESHOLD    (default: 0.50)

# Route geometry
PIPELINE_MIN_DIVERSITY_KM   (default: 15.0)
PIPELINE_MAX_DIVERSITY_KM   (default: 100.0)

# Provider radii
PIPELINE_MAPILLARY_RADIUS_M   (default: 500)
PIPELINE_WIKIMEDIA_RADIUS_M   (default: 1000)

LOG_LEVEL   (default: INFO)
```
