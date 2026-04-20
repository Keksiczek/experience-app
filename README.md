# experience-app

Aplikace pro kurátorované geo-exploration experiences nad reálnými místy světa.

Z textového promptu vytváří strukturovanou sekvenci zastávek — každá s reálnou lokalitou, mapovým kontextem, dostupnými médii a krátkým vysvětlením, proč to odpovídá promptu.

## Co aplikace dělá

Uživatel zadá volný text (např. „opuštěné průmyslové oblasti v Polsku" nebo „drsná horská sedla ve Skandinávii") a aplikace sestaví `Experience` — kurátorovaný geovýlet z ověřitelných open dat.

Aplikace **nehalucinuje fakta**. Každá zastávka je podložená strukturovanými daty ze zdrojů jako OpenStreetMap, Wikidata nebo Mapillary. Pokud data chybí, aplikace to přizná a přejde na slabší, ale stále použitelný fallback.

Pro lokální vývoj bez API klíčů použij **mock mode**: `MOCK_MODE=true` spustí celou pipeline na vzorových datech v `data/samples/` bez jediného live HTTP requestu.

## Architektura

Pipeline je lineární a deterministická:

```
Prompt → Intent → Region Discovery → Place Discovery → Media Resolution → Experience Composition → Narration
```

Každý krok loguje výsledky, může selhat kontrolovaně a předává downstream pouze ověřená data.

## Technický stack

- **Backend:** Python / FastAPI
- **Datové zdroje:** OpenStreetMap (Overpass), Mapillary, Wikidata, Wikimedia Commons, Nominatim
- **Cache:** file-based (první iterace), redis-ready interface
- **Fronted:** TBD (první iterace je API-only)

## První iterace — 3 pevné režimy

Aby byl prompt parser laditelný, první verze podporuje jen:
- `scenic_roadtrip`
- `remote_landscape`
- `abandoned_industrial`

## Dokumentace

| Dokument | Obsah |
|---|---|
| [docs/vision.md](docs/vision.md) | Produktová vize a principy |
| [docs/architecture.md](docs/architecture.md) | Technická architektura a pipeline |
| [docs/data-sources.md](docs/data-sources.md) | Datové zdroje, limity, fallbacky |
| [docs/scoring.md](docs/scoring.md) | Scoringová logika pro místa a média |
| [docs/prompts.md](docs/prompts.md) | Prompt parsing a PromptIntent model |
| [docs/test-regions.md](docs/test-regions.md) | Testovací regiony pro vývoj |
| [docs/failure-modes.md](docs/failure-modes.md) | Failure modes, fallback chain, quality gates |
| [docs/backlog.md](docs/backlog.md) | Backlog a GitHub issues |
| [docs/implementation-plan.md](docs/implementation-plan.md) | Implementační plán po iteracích |

## Quickstart (backend)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp ../.env.example ../.env          # upravit dle potřeby (MAPILLARY_API_KEY aj.)
uvicorn app.main:app --reload
```

**Lokální vývoj bez API klíčů** — mock mode (data z `data/samples/`, žádné live requesty):

```bash
MOCK_MODE=true uvicorn app.main:app --reload
# POST /experiences {"prompt": "opuštěné průmyslové oblasti v Horním Slezsku"}
```

## Struktura repozitáře

```
experience-app/
├── docs/               # Projektová dokumentace
├── backend/            # FastAPI backend
│   └── app/
│       ├── api/        # HTTP routes
│       ├── core/       # Config, logging
│       ├── models/     # Datové modely (Pydantic)
│       ├── pipeline/   # Kroky pipeline
│       ├── providers/  # Adaptery pro datové zdroje
│       ├── cache/      # Cache abstrakce
│       ├── scoring/    # Scoringová logika
│       └── jobs/       # Background jobs
├── data/
│   ├── caches/         # Lokální cache (gitignored)
│   ├── samples/        # Vzorová data pro testování
│   └── exports/        # Exporty experiences
├── experiments/        # Ad-hoc experimenty, Jupyter notebooky
└── notes/              # Pracovní poznámky, rozhodnutí
```
