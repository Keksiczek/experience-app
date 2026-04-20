# Region Registry

## Přehled

Region registry (`data/regions/region_registry.yaml`) je statický katalog geografických regionů pro MVP pipeline. Stabilizuje výběr regionu tam, kde Nominatim selže nebo kde prompt nezmíní konkrétní region.

Registry je autoritativní zdroj pro:
- Podporované módy per region
- Očekávanou kvalitu médií (Mapillary/Wikimedia coverage)
- Známá omezení OSM dat pro danou oblast
- Doporučené bounding boxy pro Overpass queries

---

## Struktura záznamu

```yaml
- region_id: alps_western           # stable identifikátor
  name: Western Alps                # display name
  aliases:                          # alternativy pro matching
    - Alps
    - Alpy
    - western alps
  country: France / Italy / Switzerland
  bbox: [lat_min, lon_min, lat_max, lon_max]
  supported_modes:
    - scenic_roadtrip
    - remote_landscape
  expected_media_coverage: high     # high | medium | low | unknown
  known_limitations:
    - "text popis omezení"
  notes: >
    Volný text pro pipeline debugging.
```

---

## Jak Region Discovery používá registry

Prioritní pořadí (viz `region_discovery.py`):

1. **Nominatim geocoding** — pro explicitně zmíněný region v promptu
2. **Registry selection** — mode-aware scoring:
   - `supported_modes` musí obsahovat aktuální mód (tvrdý filtr)
   - Bonus za `expected_media_coverage: high`
   - Penalizace za počet `known_limitations`
   - Alias match na prompt region names přidává body
3. **Static JSON fallback** — legacy `data/samples/regions.json` (last resort)

Každý vrácený `RegionCandidate` nese `decision_reasons` — seznam důvodů výběru.

**Confidence pro registry výběr:**
- Nominatim hit: confidence = 0.85–1.0
- Registry match s alias: confidence ≈ 0.70–0.85
- Registry match bez alias (jen mode match): confidence ≈ 0.50–0.60
- Static fallback: confidence = 0.35 (vždy nízká)

---

## Přehled regionů v MVP registry

### Scenic Roadtrip

| region_id | Název | Země | Media coverage | Poznámka |
|---|---|---|---|---|
| `alps_western` | Western Alps | FR/IT/CH | high | Col de l'Iseran, Gran San Bernardo |
| `alps_eastern` | Eastern Alps | AT/IT/SI | high | Grossglockner, Dolomites |
| `stelvio_pass` | Stelvio Pass Area | IT | high | Tight bbox pro přesné queries |
| `transylvanian_alps` | Transylvanian Alps | RO | medium | Transfăgărășan, Transalpina |
| `scottish_highlands` | Scottish Highlands | UK | medium | NC500, Cairngorms |
| `norway_fjords` | Norway Fjord Country | NO | medium | Trollstigen, Geiranger |

### Remote Landscape

| region_id | Název | Země | Media coverage | Poznámka |
|---|---|---|---|---|
| `iceland` | Iceland | IS | medium | Velmi řídká F-road coverage |
| `hardangervidda` | Hardangervidda | NO | low | Málo OSM POI v interiéru |
| `southwestern_us` | Southwestern US | USA | high | Grand Canyon, Canyonlands, Zion |
| `ust_urt` | Ust-Urt Plateau | KZ/UZ | low | Téměř nulový Mapillary |
| `atacama` | Atacama Desert | CL | low | Slabá coverage mimo San Pedro |
| `patagonia` | Patagonia | CL/AR | medium | Carretera Austral |

### Abandoned Industrial

| region_id | Název | Země | Media coverage | Poznámka |
|---|---|---|---|---|
| `upper_silesia` | Upper Silesia | PL | medium | Aktivní + opuštěné objekty smíchány |
| `halle_merseburg` | Halle-Merseburg | DE | medium | Chemický trojúhelník |
| `ruhr_valley` | Ruhr Valley | DE | high | Zeche Zollverein (UNESCO) |
| `donbass` | Donbas | UA | low | Konfliktní zóna — pouze data exploration |
| `north_bohemia` | North Bohemia | CZ | medium | Hnědouhelná pánev |

---

## Přidání nového regionu

1. Přidej záznam do `data/regions/region_registry.yaml`
2. Ověř bbox ručně (OpenStreetMap / overpass-turbo.eu)
3. Odhadni `expected_media_coverage` z Mapillary coverage map
4. Zapiš `known_limitations` upřímně — lepší nízká confidence než špatný výsledek
5. Přidej region aliases tak, aby odpovídaly tomu, jak ho uživatelé typicky jmenují

---

## Vztah k OSM / Overpass queries

`bbox` z registru se předává přímo do Overpass queries. Příliš velký bbox = příliš mnoho výsledků a degradace kvality. Příliš malý = žádné výsledky.

Doporučené velikosti bboxu:
- Průsmyk / specifické místo: ~0.4° × 0.5°
- Horský region: 0.5°–2° strany
- Celá země (malá): 3°–5° strany
- Plateau / pustina: 1°–3° strany

Velké boxy (> 5° strany) mohou způsobit Overpass timeout. Preferuj více menších regionů před jedním obřím.
