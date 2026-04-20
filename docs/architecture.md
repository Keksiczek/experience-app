# Technická architektura

## Přehled

Aplikace je postavená jako lineární pipeline s explicitními quality gates mezi kroky. Každý krok pipeline je samostatný modul s jasně definovaným vstupem, výstupem a sadou failure modes.

Backend je FastAPI aplikace. Zpracování experience je asynchronní job — výsledek není vrácen synchronně, ale je uložen a dostupný přes GET endpoint.

## Pipeline

```
Prompt (string)
    │
    ▼
[1] Intent Parser
    │  → PromptIntent (themes, terrain, mood, route_style, mode, ...)
    │  ✗ FAIL: prompt nesrozumitelný nebo mimo podporované módy → 400
    │
    ▼
[2] Region Discovery
    │  → RegionCandidate[] (bbox, name, source)
    │  ✗ FAIL: žádný region nenalezen → pipeline se zastaví
    │  ⚠ WARN: nízká confidence → downgrade na broader region
    │
    ▼
[3] Place Discovery
    │  → PlaceCandidate[] (lat, lon, tags, scores)
    │  ✗ FAIL: méně než MIN_PLACES míst → pipeline se zastaví
    │  ⚠ WARN: < IDEAL_PLACES míst → experience bude kratší
    │
    ▼
[4] Media Resolution
    │  → MediaCandidate[] (provider, url, license, coverage_score)
    │  ✗ FAIL: nikdy nezastaví pipeline
    │  ⚠ WARN: chybí média → fallback_level se zvýší
    │
    ▼
[5] Experience Composer
    │  → ExperienceStop[] (ordered, scored, fallback_level assigned)
    │  Logika: scoring → ranking → diversity filter → route sort
    │
    ▼
[6] Narrator
    │  → narration pro každý stop, summary pro celou experience
    │  Pravidlo: narrace smí obsahovat jen fakta z dat předchozích kroků
    │
    ▼
Experience (výsledný objekt)
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

### Job persistence

Aktuální implementace používá `InMemoryJobStore`. **Omezení:**
- Jobs jsou ztraceny při restartu procesu
- Není možné dotazovat stav z více workerů
- Neexistuje audit trail ani resumability
- Store roste bez limitu

Viz `app/jobs/job_store.py` pro `BaseJobStore` ABC a backlog položku **3.P.1** pro perzistentní implementaci.

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
