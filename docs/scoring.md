# Scoringová logika

## Přehled

Scoring je heuristický, ne ML-based. Každé místo dostane skóre v rozsahu 0.0–1.0, které určuje, jestli se dostane do výsledné experience a v jakém pořadí.

Scoring záměrně nepoužívá ML ranking v první iteraci — je jednodušší ladit, debugovat a vysvětlit výsledek.

## Výsledný score

```
final_score =
    0.35 * prompt_relevance
  + 0.25 * media_availability
  + 0.15 * scenic_value
  + 0.15 * diversity_bonus
  + 0.10 * route_coherence
```

Threshold pro zařazení do experience: `final_score >= 0.40`

---

## Složky skóre

### prompt_relevance (0.35)

Jak moc OSM tagy místa odpovídají intentu z promptu.

**Výpočet:**
- Pro každý `theme` v `PromptIntent.themes[]` se zkontroluje, jestli OSM tagy místa obsahují odpovídající tag pattern
- Score = počet matchnutých themes / celkový počet themes
- Bonus +0.1 pokud místo matchuje `route_style` (izolovanost, druh terénu)

**Příklady tag matchingu:**

| Theme | OSM tag pattern |
|---|---|
| `abandoned_industrial` | `ruins=industrial`, `disused:man_made=*`, `historic=ruins` + `building=industrial` |
| `mountain_pass` | `mountain_pass=yes`, `natural=saddle` |
| `remote` | `place=isolated_dwelling`, absence `highway=*` v okolí |
| `scenic_viewpoint` | `tourism=viewpoint`, `natural=cliff` |

**Fallback:** Pokud žádný tag neodpovídá, `prompt_relevance = 0.1` (baseline za to, že místo existuje v regionu).

---

### media_availability (0.25)

Dostupnost použitelných médií v okolí místa.

**Výpočet:**
```
media_availability =
    0.7 * mapillary_coverage_score
  + 0.3 * wikimedia_has_image
```

- `mapillary_coverage_score`: 0.0–1.0 podle počtu sekvencí v radius 500m
  - 0 sekvencí → 0.0
  - 1–2 sekvence → 0.4
  - 3–9 sekvencí → 0.7
  - 10+ sekvencí → 1.0
- `wikimedia_has_image`: 1.0 pokud Commons vrátí alespoň 1 obrázek v radius 1000m, jinak 0.0

**Poznámka:** Tato složka záměrně nesnižuje score na 0, i když média chybí. Místo může mít vysoký `prompt_relevance` a přesto být zařazeno s `fallback_level = NO_MEDIA`.

---

### scenic_value (0.15)

Heuristická hodnota krajinného nebo atmosferického potenciálu místa.

**Výpočet na základě OSM tagů:**

| Tag | Bonus |
|---|---|
| `natural=peak` | +0.8 |
| `natural=cliff` | +0.7 |
| `natural=waterfall` | +0.6 |
| `tourism=viewpoint` | +0.5 |
| `natural=valley` | +0.5 |
| `historic=ruins` | +0.4 |
| `natural=heath` nebo `natural=fell` | +0.4 |
| `landuse=industrial` + `abandoned=yes` | +0.6 |
| `place=isolated_dwelling` | +0.3 |

Maximální scenic_value = 1.0 (clamp).

**Poznámka:** Tato složka je nejsubjektivnější — je připravená pro budoucí kalibraci nebo nahrazení ML modelem.

---

### diversity_bonus (0.15)

Penalizace za přílišnou podobnost s již vybranými místy v experience.

**Výpočet:**
- Pro každý kandidát se spočítá průměrná `haversine` vzdálenost od dosud vybraných stops
- Pokud je vzdálenost < `MIN_DIVERSITY_KM` (default: 15 km): bonus = 0.0
- Pokud je vzdálenost > `MAX_DIVERSITY_KM` (default: 100 km): bonus = 0.5 (nechceme příliš rozptýlené trasy)
- Jinak: lineárně interpolovaný bonus 0.0–1.0

**Aplikace:** diversity_bonus se přepočítává iterativně při sestavování seznamu stops (greedy selection).

---

### route_coherence (0.10)

Jak moc zapadá místo do geografické logiky trasy.

**Výpočet:**
- Pokud `route_style = "linear"`: bonus za to, že místo leží na linii od startu k cíli (±30° odchylka)
- Pokud `route_style = "loop"`: bonus za rovnoměrné rozložení kolem těžiště
- Pokud `route_style = "scattered"` nebo není určen: `route_coherence = 0.5` (neutrální)

---

## Fallback level

Každý stop dostane `fallback_level` na základě dostupných dat:

| Level | Podmínky |
|---|---|
| `FULL` | Mapillary coverage + Wikidata kontext |
| `PARTIAL_MEDIA` | Wikimedia Commons místo Mapillary |
| `NO_MEDIA` | Žádné médium, jen OSM data |
| `LOW_CONTEXT` | Žádná Wikidata metadata |
| `MINIMAL` | Jen lat/lon a základní OSM tagy |

`fallback_level` je informační — nesnižuje final_score ani nevylučuje stop z experience. Ale je součástí výstupu a logů.

---

## Konfigurace vah

Váhy jsou konfigurabilní přes `app/core/config.py`:

```python
class ScoringWeights(BaseModel):
    prompt_relevance: float = 0.35
    media_availability: float = 0.25
    scenic_value: float = 0.15
    diversity_bonus: float = 0.15
    route_coherence: float = 0.10
```

Suma vah musí být 1.0 — validováno při startu aplikace.

---

## Debugging scoringu

Každý `PlaceCandidate` ve výstupu pipeline nese `score_breakdown` dict se všemi dílčími skóre. To umožňuje auditovat, proč bylo místo vybráno nebo zamítnuto.

```json
{
  "id": "osm:node:123456",
  "name": "Důl Prokop",
  "final_score": 0.72,
  "score_breakdown": {
    "prompt_relevance": 0.90,
    "media_availability": 0.40,
    "scenic_value": 0.60,
    "diversity_bonus": 0.80,
    "route_coherence": 0.50
  },
  "fallback_level": "PARTIAL_MEDIA"
}
```
