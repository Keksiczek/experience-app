# Testovací regiony

Tyto regiony jsou doporučené pro vývoj a ladění pipeline. Jsou vybrané tak, aby pokryly různé módy, různé úrovně OSM coverage a různou dostupnost médií.

---

## Regiony per mód

### scenic_roadtrip

| Region | Stát | Bbox (lat_min, lon_min, lat_max, lon_max) | Poznámka |
|---|---|---|---|
| Stelvio Pass area | Itálie/Švýcarsko | 46.3, 10.2, 46.7, 10.7 | Hustá OSM data, Mapillary coverage |
| Transylvanian Alps | Rumunsko | 45.2, 24.5, 45.8, 25.5 | Dobrá OSM, slabší Mapillary |
| Serra da Cangalha | Brazílie | -8.8, -46.5, -8.3, -46.0 | Exotika, test slabé coverage |

### remote_landscape

| Region | Stát | Bbox | Poznámka |
|---|---|---|---|
| Hardangervidda plateau | Norsko | 59.8, 7.0, 60.4, 8.0 | Dobrá data, řídká settlement |
| Ust-Urt Plateau | Kazachstán/Uzbekistán | 42.0, 55.0, 43.5, 57.0 | Test velmi slabé Mapillary coverage |
| Atacama Desert (východní část) | Chile | -23.5, -67.5, -22.0, -66.5 | Extreme remoteness |

### abandoned_industrial

| Region | Stát | Bbox | Poznámka |
|---|---|---|---|
| Horní Slezsko (Katowice area) | Polsko | 50.1, 18.8, 50.5, 19.2 | Hustá OSM data průmyslových objektů |
| Halle-Merseburg brownfields | Německo | 51.3, 11.8, 51.6, 12.2 | Dobrá Mapillary coverage |
| Donbas region (historická data) | Etika: opatrně | — | Nevhodné pro MVP kvůli bezpečnostnímu kontextu |

---

## Testovací scénáře

### Scénář A: Plná data (happy path)
- **Region:** Horní Slezsko
- **Mód:** `abandoned_industrial`
- **Očekávání:** 5+ PlaceCandidates, alespoň 3 s Mapillary coverage, fallback_level = FULL nebo PARTIAL_MEDIA

### Scénář B: Dobrá OSM, slabá media
- **Region:** Transylvánské Alpy
- **Mód:** `scenic_roadtrip`
- **Očekávání:** Místa nalezena přes Overpass, media z Wikimedia Commons, fallback_level = PARTIAL_MEDIA nebo NO_MEDIA

### Scénář C: Minimální data (degradace)
- **Region:** Kazachstánská plošina
- **Mód:** `remote_landscape`
- **Očekávání:** Pipeline nespadne, vrátí experience s fallback_level = MINIMAL nebo NO_MEDIA, quality_flag = "low_media"

### Scénář D: Ambiguous prompt
- **Prompt:** `výlet do hor`
- **Očekávání:** Parser vrátí parse_warnings, confidence < 0.5, pipeline pokračuje s degradovaným výsledkem

### Scénář E: Neznámý region
- **Prompt:** `opuštěné továrny na Antarktidě`
- **Očekávání:** RegionDiscovery nenajde bbox → pipeline abort s chybou `no_region_found`

---

## Vzorová data

Složka `data/samples/` obsahuje:

- `regions.json` — statická mapa podporovaných regionů s bbox (fallback pro Nominatim)
- `osm_response_slezsko.json` — ukázkový Overpass výsledek pro scénář A
- `mapillary_response_sample.json` — ukázkový Mapillary response
- `wikimedia_response_sample.json` — ukázkový Wikimedia geosearch response

Tato data umožňují testovat pipeline bez živých API calls (mock mode).

---

## Jak přidat nový testovací region

1. Přidej bbox do `data/samples/regions.json`
2. Přidej záznam do tabulky výše s poznámkou o coverage
3. Doporučeno: stáhni ukázkový Overpass response a ulož do `data/samples/`
4. Přidej testovací scénář do `backend/tests/`
