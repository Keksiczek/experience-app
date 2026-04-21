"""Wikidata provider — entity context via SPARQL geosearch + search API fallback.

Primary path: SPARQL wikibase:around service finds entities within 500 m of
(lat, lon). Fallback: wbsearchentities REST API searched by place name.

Cache TTL: 7 days (place→Wikidata mapping is stable).
Rate limit: 1 req/s enforced via module-level timestamp (same pattern as Nominatim).
"""

import asyncio
import time
from typing import Any

from app.cache.base import BaseCache
from app.core.config import settings
from app.core.logging import get_logger
from app.models.place import WikidataContext
from app.providers.base import BaseProvider, ProviderError

logger = get_logger(__name__)

WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
WIKIDATA_SEARCH_API = "https://www.wikidata.org/w/api.php"
USER_AGENT = "experience-app/1.0 (geo-exploration; contact@example.com)"

_GEO_CONTEXT_TTL = 7 * 24 * 3600   # 7 days
_RATE_INTERVAL = 1.1                 # seconds between SPARQL requests

_LAST_SPARQL_TIME: float = 0.0

# SPARQL: find physical entities within 0.5 km, exclude humans (Q5),
# grab instance-of labels, image, heritage designation, sitelinks count.
_SPARQL_GEO_TEMPLATE = """\
SELECT DISTINCT ?item ?itemLabel ?itemDescription ?instanceLabel ?image ?heritage ?sitelinks WHERE {{
  SERVICE wikibase:around {{
    ?item wdt:P625 ?location.
    bd:serviceParam wikibase:center "Point({lon} {lat})"^^geo:wktLiteral.
    bd:serviceParam wikibase:radius "0.5".
  }}
  FILTER NOT EXISTS {{ ?item wdt:P31 wd:Q5. }}
  OPTIONAL {{ ?item wdt:P31 ?instance. }}
  OPTIONAL {{ ?item wdt:P18 ?image. }}
  OPTIONAL {{ ?item wdt:P1435 ?heritage. }}
  OPTIONAL {{ ?item wikibase:sitelinks ?sitelinks. }}
  SERVICE wikibase:label {{
    bd:serviceParam wikibase:language "cs,en".
    ?item rdfs:label ?itemLabel.
    ?item schema:description ?itemDescription.
    ?instance rdfs:label ?instanceLabel.
  }}
}}
LIMIT 5
"""


class WikidataProvider(BaseProvider):
    def __init__(self, cache: BaseCache) -> None:
        super().__init__(cache)

    @property
    def name(self) -> str:
        return "wikidata"

    @property
    def ttl_seconds(self) -> int:
        return settings.cache_ttl_wikidata

    def cache_key(self, params: dict[str, Any]) -> str:
        return self._make_cache_key("wikidata", params)

    async def _fetch_live(self, params: dict[str, Any]) -> Any:
        """Used by the legacy fetch_entity_context path only."""
        query = params.get("sparql", "")
        return await self._http_get(
            WIKIDATA_SPARQL,
            params={"query": query, "format": "json"},
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/sparql-results+json",
            },
            timeout=60.0,
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def fetch_entity_context(self, wikidata_id: str) -> dict[str, str]:
        """Fetch label + description for a Wikidata QID (legacy, kept for compat)."""
        sparql = f"""
SELECT ?label ?description WHERE {{
  wd:{wikidata_id} rdfs:label ?label .
  OPTIONAL {{ wd:{wikidata_id} schema:description ?description . }}
  FILTER(LANG(?label) IN ("en", "cs"))
}}
LIMIT 2
"""
        try:
            raw = await self.fetch({"sparql": sparql})
        except ProviderError as e:
            logger.warning("wikidata_failed", entity=wikidata_id, reason=str(e))
            return {}

        bindings = raw.get("results", {}).get("bindings", [])
        if not bindings:
            return {}

        first = bindings[0]
        return {
            "label": first.get("label", {}).get("value", ""),
            "description": first.get("description", {}).get("value", ""),
            "wikidata_id": wikidata_id,
        }

    async def fetch_context_for_place(
        self,
        place_id: str,
        lat: float,
        lon: float,
        name: str = "",
    ) -> WikidataContext | None:
        """Return WikidataContext for a place; never raises — returns None on any error."""
        cache_key = self._make_cache_key("wikidata_geo", {"pid": place_id})

        cached = await self._cache.get(cache_key)
        if cached is not None:
            # Empty dict stored as "tried, found nothing"
            return WikidataContext(**cached) if cached else None

        try:
            ctx = await self._sparql_geosearch(lat, lon)
            if ctx is None and name:
                ctx = await self._search_by_name(name)
        except Exception as e:
            logger.warning(
                "wikidata_context_failed",
                place_id=place_id,
                reason=str(e),
            )
            return None

        value: dict[str, Any] = ctx.model_dump() if ctx else {}
        await self._cache.set(cache_key, value, _GEO_CONTEXT_TTL)
        return ctx

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _sparql_geosearch(self, lat: float, lon: float) -> WikidataContext | None:
        global _LAST_SPARQL_TIME

        # Enforce 1 req/s
        elapsed = time.monotonic() - _LAST_SPARQL_TIME
        if elapsed < _RATE_INTERVAL:
            await asyncio.sleep(_RATE_INTERVAL - elapsed)
        _LAST_SPARQL_TIME = time.monotonic()

        query = _SPARQL_GEO_TEMPLATE.format(lat=lat, lon=lon)
        try:
            raw = await self._http_get(
                WIKIDATA_SPARQL,
                params={"query": query, "format": "json"},
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/sparql-results+json",
                },
                timeout=60.0,
            )
        except ProviderError as e:
            logger.debug("wikidata_sparql_failed", lat=lat, lon=lon, reason=str(e))
            return None

        bindings = raw.get("results", {}).get("bindings", [])
        return _parse_geo_bindings(bindings)

    async def _search_by_name(self, name: str) -> WikidataContext | None:
        try:
            raw = await self._http_get(
                WIKIDATA_SEARCH_API,
                params={
                    "action": "wbsearchentities",
                    "search": name,
                    "language": "cs",
                    "limit": "3",
                    "format": "json",
                    "type": "item",
                },
                headers={"User-Agent": USER_AGENT},
                timeout=30.0,
            )
        except ProviderError as e:
            logger.debug("wikidata_search_failed", name=name, reason=str(e))
            return None

        results = raw.get("search", [])
        if not results:
            return None

        first = results[0]
        label = first.get("label", "")
        return WikidataContext(
            wikidata_id=first.get("id"),
            description=first.get("description") or None,
            raw_labels={"cs": label, "en": label},
        )


def _parse_geo_bindings(bindings: list[dict[str, Any]]) -> WikidataContext | None:
    if not bindings:
        return None

    items: dict[str, dict[str, Any]] = {}

    for b in bindings:
        item_uri = b.get("item", {}).get("value", "")
        if not item_uri:
            continue
        qid = item_uri.split("/")[-1]

        if qid not in items:
            items[qid] = {
                "qid": qid,
                "label_cs": "",
                "label_en": "",
                "description": b.get("itemDescription", {}).get("value", "") or "",
                "instance_of": [],
                "image_url": b.get("image", {}).get("value"),
                "heritage": b.get("heritage") is not None,
                "sitelinks": 0,
            }

        # itemLabel may carry xml:lang in the binding
        label_val = b.get("itemLabel", {}).get("value", "")
        label_lang = b.get("itemLabel", {}).get("xml:lang", "")
        if label_lang == "cs":
            items[qid]["label_cs"] = label_val
        elif label_lang == "en":
            items[qid]["label_en"] = label_val
        elif label_val and not items[qid]["label_en"]:
            items[qid]["label_en"] = label_val

        sitelinks_raw = b.get("sitelinks", {}).get("value", "0")
        try:
            items[qid]["sitelinks"] = max(items[qid]["sitelinks"], int(sitelinks_raw or "0"))
        except (ValueError, TypeError):
            pass

        instance_label = b.get("instanceLabel", {}).get("value")
        if instance_label and instance_label not in items[qid]["instance_of"]:
            items[qid]["instance_of"].append(instance_label)

    if not items:
        return None

    best = max(items.values(), key=lambda x: x["sitelinks"])
    tourism_score = min(1.0, best["sitelinks"] / 50)

    return WikidataContext(
        wikidata_id=best["qid"],
        description=best["description"] or None,
        instance_of=best["instance_of"],
        heritage_status="listed" if best["heritage"] else None,
        image_url=best["image_url"],
        tourism_score=tourism_score,
        raw_labels={
            "cs": best["label_cs"],
            "en": best["label_en"],
        },
    )
