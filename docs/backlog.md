# Backlog

Backlog je organizovaný do iterací. Každá iterace má jasný cíl a definici „hotovo".

---

## Iterace 0 — Projekt foundations (aktuální)

**Cíl:** Repo je nachystané pro vývoj. Architektura a dokumentace jsou dostatečně jasné, aby mohl začít vývoj bez nutnosti velkých přepracování.

| # | Úkol | Typ | Stav |
|---|---|---|---|
| 0.1 | Navrhnout adresářovou strukturu | docs | ✅ hotovo |
| 0.2 | Napsat vision.md, architecture.md | docs | ✅ hotovo |
| 0.3 | Zdokumentovat datové zdroje a fallback chain | docs | ✅ hotovo |
| 0.4 | Zdokumentovat scoring logiku | docs | ✅ hotovo |
| 0.5 | Zdokumentovat failure modes a quality gates | docs | ✅ hotovo |
| 0.6 | Připravit backend kostru (FastAPI, modely, provider ABC) | backend | ✅ hotovo |
| 0.7 | Připravit GitHub issues pro Iteraci 1 | management | ⏳ |

---

## Iterace 1 — Funkční pipeline pro jeden mód (spike)

**Cíl:** End-to-end pipeline pro mód `abandoned_industrial` v testovacím regionu Horní Slezsko. Výsledek musí být použitelný, i když data jsou nekompletní.

**Definice „hotovo":**
- `POST /experiences` s promptem vrátí job_id
- `GET /experiences/{id}` vrátí Experience s alespoň 3 stops
- Každý stop má lat, lon, name, why_here, fallback_level
- Pipeline loguje každý krok strukturovaně
- Cache funguje — druhý identický request je výrazně rychlejší

| # | Úkol | Typ |
|---|---|---|
| 1.1 | Implementovat Intent Parser (keyword matching, 3 módy) | backend |
| 1.2 | Implementovat Nominatim adapter + file cache | backend |
| 1.3 | Implementovat Overpass adapter pro `abandoned_industrial` tagy | backend |
| 1.4 | Implementovat Mapillary adapter (coverage score) | backend |
| 1.5 | Implementovat Wikimedia Commons adapter (fallback) | backend |
| 1.6 | Implementovat scoring engine (heuristický) | backend |
| 1.7 | Implementovat Experience Composer (greedy selection, diversity) | backend |
| 1.8 | Implementovat základní Narrator (template-based) | backend |
| 1.9 | Implementovat background job orchestrator | backend |
| 1.10 | Implementovat FastAPI routes (POST/GET experience) | backend |
| 1.11 | Napsat integrační test pro scénář A (happy path, Slezsko) | test |
| 1.12 | Napsat integrační test pro scénář C (degradace, Kazachstán) | test |
| 1.13 | Nahrát vzorová data (mock responses) do data/samples/ | data |

---

## Iterace 2 — Rozšíření na všechny 3 módy

**Cíl:** Pipeline funguje pro všechny 3 módy. Parser je robustní pro různé formulace promptů.

| # | Úkol | Typ |
|---|---|---|
| 2.1 | Rozšířit Overpass tagy pro `scenic_roadtrip` | backend |
| 2.2 | Rozšířit Overpass tagy pro `remote_landscape` | backend |
| 2.3 | Přidat Wikidata adapter pro kontext míst | backend |
| 2.4 | Rozšířit scoring o context_score z Wikidata | backend |
| 2.5 | Přidat route_coherence výpočet (linear/loop/scattered) | backend |
| 2.6 | Přidat quality_flags do Experience výstupu | backend |
| 2.7 | Otestovat všechny testovací scénáře (A–E) | test |
| 2.8 | Přidat `/health` endpoint s provider status | backend |
| 2.9 | Zdokumentovat výstupní formát API | docs |

---

## Iterace 3 — Stabilizace a observability

**Cíl:** Pipeline je připravena pro první uživatelské testování. Logging je čitelný, chyby jsou srozumitelné.

| # | Úkol | Typ |
|---|---|---|
| 3.1 | Přidat structured logging (structlog) do všech kroků | backend |
| 3.2 | Přidat score_breakdown do PlaceCandidate výstupu | backend |
| 3.3 | Implementovat retry logic s exponential backoff pro všechny providers | backend |
| 3.4 | Přidat mock mode (pipeline běží na sample datech bez live API) | backend |
| 3.5 | Přidat základní rate limiter pro Nominatim (1 req/s) | backend |
| 3.6 | Přidat konfiguraci přes env variables + validaci při startu | backend |
| 3.7 | Napsat unit testy pro scoring engine | test |
| 3.8 | Napsat unit testy pro Intent Parser | test |

---

## Backlog — budoucí iterace (nerozplánované)

Tyto položky jsou zaznamenány, ale nepatří do prvních 3 iterací:

- **Narrator upgrade:** LLM-assisted narration (Claude API) s grounding validací
- **Prompt upgrade:** LLM-assisted prompt parsing pro poetické/vágní prompty
- **Redis cache:** Nahradit file cache Redisem
- **Frontend:** Mapový viewer pro Experience (MapLibre nebo Leaflet)
- **MapillaryJS integration:** Inline street-level viewer místo statického URL
- **User feedback:** Možnost označit stop jako irelevantní → zpětná vazba do scoringu
- **Multi-region support:** Experience pokrývající více regionů (cross-border roadtrip)
- **Export:** Export experience jako GPX nebo GeoJSON
- **API key management:** Rotace Mapillary klíčů, monitoring kvóty
- **Self-hosted Nominatim:** Pro vyšší rate limity
- **Penalizace turistických trap:** Downranking přeplněných turistických míst

---

## Prioritizační principy

1. Debuggovatelnost před featury — každá nová feature musí být logovatelná
2. Fallback chain před happy path — nejdřív ošetřit selhání, pak optimalizovat úspěch
3. Jeden mód perfektně před třemi módů průměrně
4. Žádná halucinace v žádné iteraci — nepřijatelné v jakékoli verzi
