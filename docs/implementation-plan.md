# Implementační plán

## Přístup

Vývoj jde v iteracích, každá buduje na předchozí. Nová vrstva se přidává teprve když předchozí funguje a je otestovaná. Žádné half-finished features.

---

## Iterace 1 — Funkční pipeline (spike)

**Trvání:** ~2–3 týdny sólový vývoj nebo 1 týden ve dvou

### Pořadí implementace

Pořadí je záměrné — každý krok je testovatelný samostatně.

```
1. Datové modely (models/)
   → Pydantic modely pro všechny entity
   → Bez business logiky, jen struktury a validace
   → Lze testovat hned

2. Cache (cache/)
   → BaseCache ABC
   → FileCache implementace
   → Test: uložit, přečíst, expirovat

3. BaseProvider ABC (providers/base.py)
   → Rozhraní pro všechny adaptery
   → Dependency inject cache

4. Nominatim adapter (providers/nominatim.py)
   → Geocoding region → bbox
   → Rate limiting (1 req/s)
   → Integrace s cache

5. Overpass adapter (providers/osm.py)
   → Fetch POI pro bbox + tag set
   → Parser Overpass JSON → PlaceCandidate
   → Test na sample datech

6. Intent Parser (pipeline/intent_parser.py)
   → Keyword matching pro 3 módy
   → Extrakce regionu
   → Unit testy

7. Region Discovery (pipeline/region_discovery.py)
   → Volá Nominatim, fallback na statická data
   → Výstup: RegionCandidate[]

8. Place Discovery (pipeline/place_discovery.py)
   → Volá Overpass pro bbox z RegionCandidate
   → Tag filtering per mód
   → Výstup: PlaceCandidate[]

9. Mapillary adapter (providers/mapillary.py)
   → Coverage score pro souřadnice
   → Vyžaduje API key

10. Wikimedia adapter (providers/wikimedia.py)
    → Geosearch pro obrázky v okolí
    → Fallback logic

11. Media Resolution (pipeline/media_resolution.py)
    → Pro každý PlaceCandidate: Mapillary → Wikimedia → NO_MEDIA
    → Přiřazení MediaCandidate a fallback_level

12. Scoring Engine (scoring/scorer.py)
    → Výpočet prompt_relevance, media_availability, scenic_value
    → score_breakdown per place

13. Experience Composer (pipeline/experience_composer.py)
    → Greedy selection s diversity bonusem
    → Threshold logic
    → Výstup: ExperienceStop[]

14. Narrator (pipeline/narrator.py)
    → Template-based narration z dostupných dat
    → Jen fakta, žádná halucinace

15. Job Orchestrator (jobs/experience_job.py)
    → Sekvence kroků 6–14
    → Error handling, job status updates
    → Logování každého kroku

16. FastAPI routes (api/routes/)
    → POST /experiences → spustit job
    → GET /experiences/{id} → vrátit výsledek nebo status
    → GET /health → provider status

17. Integrace a end-to-end test
    → Scénář A (happy path, Slezsko)
    → Scénář C (degradace, Kazachstán)
```

---

## Technical Spike — Overpass + Scoring

Před plnou implementací doporučuji mini-spike v `experiments/`:

1. Stáhnout Overpass response pro Horní Slezsko (abandoned_industrial tagy)
2. Ručně spočítat scoring pro 5 míst
3. Ověřit, že scorer dává intuitivně správné výsledky
4. Zpřísnit nebo uvolnit tag patterns na základě výsledků

Spike by měl trvat 2–4 hodiny a ušetří přepracování scoring logiky.

---

## Konvence

### Pojmenování

- Modely: PascalCase (`PromptIntent`, `PlaceCandidate`)
- Kroky pipeline: snake_case funkce (`parse_intent`, `discover_places`)
- Providery: snake_case třídy (`NominatimProvider`, `OverpassProvider`)
- Konstanty: UPPER_SNAKE_CASE (`MIN_PLACES`, `CACHE_TTL_NOMINATIM`)

### Typy

- Všude Pydantic modely, žádné raw dict pro business data
- `list[PlaceCandidate]` ne `list[dict]`
- Async/await pro všechny HTTP calls

### Testování

- Unit testy pro: parser, scorer, každý provider (s mock HTTP)
- Integrační testy pro: celá pipeline na sample datech (mock providers)
- Live testy (volitelné): end-to-end s reálnými API na testovacích regionech

### Error handling

- Custom exceptions per typ selhání (`RegionNotFoundError`, `TooFewPlacesError`)
- Všechny HTTP chyby zachyceny v provideru, nikoli v pipeline kroku
- Pipeline krok nikdy necachuje výjimku — buď propaguje, nebo vrací prázdný výsledek s varováním

---

## Infrastruktura (první iterace — minimální)

Žádné Docker, žádné CI/CD v Iteraci 1. Jen:

```bash
python -m venv .venv
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

`.env` soubor pro lokální konfiguraci (gitignored):
```
MAPILLARY_API_KEY=...
CACHE_DIR=./data/caches
LOG_LEVEL=DEBUG
```

---

## Kdy přejít na Iteraci 2

Kritéria pro konec Iterace 1:

- [ ] End-to-end test pro scénář A projde bez live API (na sample datech)
- [ ] End-to-end test pro scénář C projde bez pádu pipeline
- [ ] Log z jednoho requestu je čitelný a debuggovatelný
- [ ] Cache funguje — druhý request je > 5× rychlejší
- [ ] Žádný stop neobsahuje halucinovaný text
