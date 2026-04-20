from typing import Any

from app.cache.base import BaseCache
from app.core.config import settings
from app.core.logging import get_logger
from app.providers.base import BaseProvider, ProviderError

logger = get_logger(__name__)

WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
USER_AGENT = "experience-app/0.1 (geo-exploration; contact@example.com)"


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

    async def fetch_entity_context(self, wikidata_id: str) -> dict[str, str]:
        """Fetch label and description for a Wikidata entity ID (e.g. Q12345)."""
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
