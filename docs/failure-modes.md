# Failure Modes, Fallback Chain a Quality Gates

## Princip

Pipeline nesmí tiše selhat. Každý failure mode má definované chování: buď pipeline pokračuje s degradovaným výsledkem, nebo se zastaví s čitelnou chybou. Není přijatelné vrátit experience s halucinovanými daty.

---

## Failure Modes per krok

### [1] Intent Parser

| Selhání | Příčina | Chování |
|---|---|---|
| `AMBIGUOUS_MODE` | Dva módy stejně pravděpodobné | Pipeline pokračuje, `parse_warnings += ["ambiguous_mode"]`, nízká confidence |
| `NO_MODE_DETECTED` | Žádné keyword nesedí | `400 Bad Request`: "Prompt neodpovídá žádnému podporovanému módu" |
| `TOO_VAGUE` | Prompt < 5 slov, žádné klíčové info | Pipeline pokračuje, `confidence < 0.4`, výsledek označen jako `low_confidence` |
| `UNSUPPORTED_MODE_REQUEST` | Uživatel explicitně žádá nepodporovaný mód | `400 Bad Request` s nápovědou |

### [2] Region Discovery

| Selhání | Příčina | Chování |
|---|---|---|
| `NOMINATIM_TIMEOUT` | API nedostupné nebo pomalé | Retry 3× s backoff, pak fallback na statické `regions.json` |
| `NOMINATIM_NO_RESULT` | Region z promptu nenalezen | Fallback na statické `regions.json` → pokus o heuristický match |
| `STATIC_FALLBACK_NO_MATCH` | Region nelze odvodit z ničeho | `PIPELINE_ABORT`: "Region nelze určit" — job_status = failed |
| `BBOX_TOO_LARGE` | Region je kontinent nebo příliš velký | Automatické zmenšení na subregion nebo `400 Bad Request` |

### [3] Place Discovery (Overpass)

| Selhání | Příčina | Chování |
|---|---|---|
| `OVERPASS_TIMEOUT` | Dotaz trvá příliš dlouho | Retry s jednodušším dotazem (méně tagů), pak abort |
| `OVERPASS_RATE_LIMIT` | 429 response | Exponential backoff (2s, 4s, 8s), pak abort |
| `TOO_FEW_PLACES` | < `MIN_PLACES` (3) výsledků | `PIPELINE_ABORT`: "Nedostatek míst pro experience" |
| `SUBOPTIMAL_PLACES` | 3–7 výsledků (pod `IDEAL_PLACES` = 8) | Pipeline pokračuje, experience bude kratší, `quality_flag = "few_places"` |
| `NO_RELEVANT_TAGS` | Výsledky mají nulový prompt_relevance | Warning, scoring penalizuje, experience může být slabá |

### [4] Media Resolution

| Selhání | Příčina | Chování |
|---|---|---|
| `MAPILLARY_AUTH_ERROR` | Chybí nebo neplatný API key | Log error, skip Mapillary, přejít přímo na Wikimedia |
| `MAPILLARY_NO_COVERAGE` | 0 sekvencí v okolí | Fallback na Wikimedia Commons |
| `WIKIMEDIA_EMPTY` | 0 obrázků v okolí | `fallback_level = NO_MEDIA` pro daný stop |
| `MAPILLARY_RATE_LIMIT` | 429 response | Backoff + cache existujících výsledků, skip pro zbývající místa |
| `MEDIA_IRRELEVANT` | Výsledky jsou geograficky moc daleko | Distance filter vyfiltruje, fallback na NO_MEDIA |

Tenhle krok **nikdy* nezastaví pipeline**. Media jsou optional.

### [5] Experience Composer

| Selhání | Příčina | Chování |
|---|---|---|
| `INSUFFICIENT_SCORED_PLACES` | Všechna místa pod threshold 0.40 | Threshold se sníží na 0.25 (emergency fallback), pak abort |
| `DIVERSITY_IMPOSSIBLE` | Všechna místa v malém clusteru | Diversity bonus se ignoruje, vezme top N by score |
| `ROUTE_SORT_FAILED` | Geometrie trasy nesedí | Fallback na sort by score (bez geografické logiky) |

### [6] Narrator

| Selhání | Příčina | Chování |
|---|---|---|
| `NO_NARRATION_DATA` | Stop nemá žádná strukturovaná data pro naraci | Generický template: "Lokalita {name} ({lat}, {lon}). Bez dostupných dat." |
| `GROUNDING_VIOLATION` | Narrace by musela halucinovat (detekce v budoucí iteraci) | Log warning, použít jen ověřená fakta |

---

## Fallback Chain — vizualizace

```
Geocoding:
  Nominatim → statické regions.json → ABORT

Place Discovery:
  Overpass (plný dotaz) → Overpass (jednodušší dotaz) → ABORT

Media:
  Mapillary → Wikimedia Commons → NO_MEDIA (stop pokračuje bez média)

Context:
  Wikidata → žádný kontext (stop pokračuje s nižším context_score)

Narration:
  Plná narrace z dat → template s dostupnými fakty → generický placeholder
```

---

## Quality Flags

`Experience` objekt nese `quality_flags: list[str]` — souhrn signálů o kvalitě výsledku:

| Flag | Podmínka |
|---|---|
| `low_confidence_intent` | Parser confidence < 0.5 |
| `no_region_specified` | `preferred_regions = []` |
| `few_places` | Méně než 5 stops ve výsledku |
| `low_media` | > 50% stops má `fallback_level = NO_MEDIA` |
| `emergency_threshold` | Composer musel snížit scoring threshold na 0.25 |
| `partial_narration` | Alespoň 1 stop má generický narration template |

---

## Job Status

Background job pro generování experience má tyto stavy:

```
pending → running → completed
                 → failed (s error_code a error_message)
                 → completed_with_warnings (s quality_flags)
```

`completed_with_warnings` je platný výstup — experience existuje, ale uživatel by měl vědět o omezeních.

---

## Logování

Každý failure a fallback je logován na úrovni `WARNING` nebo `ERROR` ve structured JSON:

```json
{
  "event": "media_fallback",
  "step": "media_resolution",
  "place_id": "osm:node:123456",
  "primary_provider": "mapillary",
  "fallback_provider": "wikimedia",
  "reason": "no_coverage",
  "fallback_level": "PARTIAL_MEDIA",
  "duration_ms": 342
}
```

Logy jsou záměrně verbose — debugging má být jednoduchý.

---

## Co pipeline nikdy nesmí udělat

1. Vrátit `why_here` nebo `narration` s faktem, který není podložen daty
2. Silently ignorovat chybu providera bez záznamu v logu
3. Vrátit `Experience` bez `fallback_level` na každém stopu
4. Selhat bez čitelné chybové zprávy v `job_status`
