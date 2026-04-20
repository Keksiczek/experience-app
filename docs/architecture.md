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

## Quality Gates

| Gate | Podmínka | Akce při selhání |
|---|---|---|
| intent_valid | mode je jeden ze 3 podporovaných | 400, pipeline se nespustí |
| region_found | alespoň 1 RegionCandidate | pipeline abort, error v job status |
| min_places | ≥ 3 PlaceCandidates | pipeline abort |
| ideal_places | ≥ 8 PlaceCandidates | warning, kratší experience |
| media_partial | < 50% stops má média | experience.quality_flag = "low_media" |
| narration_grounded | narrace neobsahuje informaci bez data source | validátor (budoucí iterace) |

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

Vše přes environment variables, defaulty v `core/config.py`:
- `MAPILLARY_API_KEY`
- `CACHE_DIR`
- `CACHE_TTL_*` per provider
- `PIPELINE_MIN_PLACES`
- `PIPELINE_IDEAL_PLACES`
- `LOG_LEVEL`
