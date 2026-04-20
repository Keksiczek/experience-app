# Datové zdroje

## Provider operations — přehledová tabulka

| Provider | Účel | Autentizace | Rate limit | Cache TTL | Retry strategie | Fallback role | Self-host možnost |
|---|---|---|---|---|---|---|---|
| **Nominatim** | Geocoding regionů | žádná | 1 req/s (striktní) | 7 dní | 1 s throttle, 3× retry s backoff | statické `regions.json` | ✅ openstreetmap/nominatim Docker image |
| **Overpass** | Primární discovery míst z OSM | žádná | ~1 req/2 s, soft | 24 hodin | 3× retry (2s, 4s, 8s), jednodušší dotaz při timeout | — (tvrdý gate) | ✅ wiktorn/overpass-api Docker image |
| **Mapillary** | Street-level imagery, coverage score | OAuth client token (`MAPILLARY_API_KEY`) | 50 000 req/den | 6 hodin | 3× retry s backoff | Wikimedia Commons | ❌ (komerční infrastruktura) |
| **Wikimedia Commons** | Geotagované fotografie | žádná | ~10 req/s doporučeno | 24 hodin | 3× retry s backoff | NO_MEDIA | ✅ MediaWiki Docker image |
| **Wikidata** | Kontextová metadata, popisy | žádná (User-Agent required) | 1 req/5 s anonymní | 48 hodin | 3× retry s backoff; timeout 60 s | context skipped, nižší context_score | ✅ Wikibase Docker image |

### Poznámky k rate limitům

- **Nominatim** má rate limit enforcovaný serverem — překročení vede k dočasnému banu IP. Throttle je implementovaný v `providers/nominatim.py` jako modul-level `_LAST_REQUEST_TIME`.
- **Overpass** nemá striktní rate limit, ale zátěžové dotazy na velké bbox nebo komplexní tagy vedou k timeoutu. Doporučený `timeout=45` parametr v dotazu.
- **Mapillary** 50 000/den = ~34 req/min. Při normálním provozu (1 request per stop per experience) není limit problém, ale je nutné monitorovat při testování.
- **Wikidata** je anonymní limit 1 req/5 s velmi volný v praxi — doporučeno dodržovat a nastavit descriptivní `User-Agent`.

---

## Přehled a fallback chain

Každý provider je ohodnocen podle coverage, spolehlivosti a dostupnosti. Fallback chain je explicitní — pipeline vždy ví, z jakého zdroje pochází každý kus dat.

```
Place discovery:
  1. OpenStreetMap / Overpass   ← primární
  2. Wikidata                   ← doplňkový kontext

Geocoding:
  1. Nominatim                  ← primární

Media:
  1. Mapillary                  ← primární (street-level)
  2. Wikimedia Commons          ← fallback (geotagované fotografie)
  3. [žádné médium]             ← fallback_level = NO_MEDIA

Context / metadata:
  1. Wikidata                   ← primární
  2. Wikimedia Commons          ← fallback
```

---

## OpenStreetMap / Overpass API

**Použití:** Primární zdroj pro discovery míst — POI, přírodní objekty, ruiny, průmyslové objekty, cesty, sídla.

**Endpoint:** `https://overpass-api.de/api/interpreter`

**Limity:**
- Rate limit: ne víc než 1 request za 2 sekundy per IP
- Timeout: dotazy nad komplexní region mohou trvat 10–60 sekund
- Velké bbox → velký payload → nutná paginace nebo omezení tagů

**Klíčové tagy pro jednotlivé módy:**

| Mód | OSM tagy |
|---|---|
| `scenic_roadtrip` | `natural=peak`, `natural=valley`, `natural=cliff`, `tourism=viewpoint`, `highway=scenic` |
| `remote_landscape` | `natural=bare_rock`, `natural=heath`, `natural=fell`, `landuse=wilderness`, `place=isolated_dwelling` |
| `abandoned_industrial` | `historic=ruins`, `ruins=industrial`, `man_made=works` + `disused=yes`, `landuse=industrial` + `abandoned=yes` |

**Caching:** 24 hodin, klíč = hash(query + bbox).

**Fallback při výpadku:** Pokud Overpass timeout nebo 429 → retry s exponential backoff (2s, 4s, 8s), pak abort kroku.

---

## Mapillary

**Použití:** Primární zdroj street-level imagery. Pokrytí je nerovnoměrné — dobré v západní Evropě, slabé v odlehlých regionech.

**Endpoint:** `https://graph.mapillary.com/` (Graph API v4)

**Autentizace:** Vyžaduje `MAPILLARY_API_KEY` (client token).

**Limity:**
- Rate limit: 50 000 requestů/den na token
- Coverage: dostupnost nelze garantovat mimo hlavní silnice a turistické trasy

**Co fetchujeme:**
- Sequences v okolí souřadnic místa (radius 500m)
- První dostupný obrázek sekvence jako `preview_url`
- `viewer_ref` = sequence key pro případný Mapillary viewer

**Coverage score:** počet sekvencí v okolí / normalizovaný threshold. 0.0 = žádné, 1.0 = hustá coverage.

**Fallback při výpadku nebo 0 coverage:** přechod na Wikimedia Commons.

---

## Wikimedia Commons / MediaWiki Geosearch

**Použití:** Fallback zdroj pro geotagované fotografie. Pokrytí je nerovnoměrné, ale Commons má obsah pro mnoho odlehlých míst, která Mapillary nemá.

**Endpoint:** `https://commons.wikimedia.org/w/api.php`

**Parametry dotazu:**
```
action=query
list=geosearch
gscoord={lat}|{lon}
gsradius=1000
gslimit=10
gsnamespace=6  (File: namespace)
```

**Limity:**
- Rate limit: max 50 requestů/sekund (v praxi doporučeno max 10/s)
- Výsledky nejsou garantovaně relevantní k tématu — nutná filtrace

**Co fetchujeme:**
- `title`, `lat`, `lon`, `dist` (distance from query point)
- Thumbnail URL přes `imageinfo` API

**Caching:** 24 hodin.

**Fallback při prázdném výsledku:** `fallback_level = NO_MEDIA`.

---

## Wikidata Query Service

**Použití:** Metadata a kontext pro místa — historický kontext, popis, kategorie. Doplňkový zdroj, ne primární discovery.

**Endpoint:** `https://query.wikidata.org/sparql`

**Limity:**
- Rate limit: max 1 request za 5 sekund pro anonymní přístupy; doporučen User-Agent header
- Timeout: 60 sekund pro složité SPARQL dotazy
- Výsledky jsou závislé na kvalitě Wikidata — nekompletní a nerovnoměrné

**Typické dotazy:**
- Fetch entity pro dané OSM `wikidata` tag hodnoty
- Geosearch entit v bbox podle typu (průmyslové lokality, přírodní objekty)

**Caching:** 48 hodin.

**Fallback:** pokud Wikidata nevrátí kontext, `context_score` se sníží, ale pipeline pokračuje.

---

## Nominatim

**Použití:** Geocoding — převod promptem naznačeného regionu (název oblasti, státu, pohoří) na bbox.

**Endpoint:** `https://nominatim.openstreetmap.org/search`

**Limity:**
- Rate limit: max 1 request za sekundu (striktně dodržovat)
- Nelze použít pro komerční vysoký traffic bez self-hosted instance

**User-Agent:** Nominatim vyžaduje identifikační `User-Agent` header.

**Caching:** 7 dní (geocoding výsledky jsou stabilní).

**Fallback:** pokud Nominatim nevrátí výsledek → pipeline zkusí RegionDiscovery ze statické mapy regionů (viz `data/samples/regions.json`).

---

## Limity a rizika

| Riziko | Zdroj | Mitigace |
|---|---|---|
| Overpass timeout na velký region | OSM | bbox omezení, timeout parametr v dotazu |
| Mapillary bez coverage | Mapillary | fallback na Wikimedia, explicitní fallback_level |
| Nominatim rate limit | Nominatim | 1s throttle, agresivní caching |
| Wikidata nekompletní data | Wikidata | context je optional, nesnižuje pipeline výsledek |
| Wikimedia irelevantní výsledky | Commons | distance filter + ruční threshold |
| Výpadek externího API | všechny | retry s backoff, abort kroku, job status error |

---

## Přidání nového providera

Každý provider implementuje `BaseProvider` z `app/providers/base.py`. Minimální rozhraní:

```python
class BaseProvider(ABC):
    @abstractmethod
    async def fetch(self, params: dict) -> list[dict]:
        ...

    @abstractmethod
    def cache_key(self, params: dict) -> str:
        ...

    @property
    @abstractmethod
    def ttl_seconds(self) -> int:
        ...
```

Cache je inject-ovaná, provider neví, jak je výsledek uložen.
