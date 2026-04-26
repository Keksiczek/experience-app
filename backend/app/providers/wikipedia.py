"""Wikipedia REST summary provider.

Given a Wikidata QID, fetches a 1-paragraph summary from the corresponding
Wikipedia article (preferring Czech, falling back to English).

Implementation:
1. Fetch the Wikidata entity JSON via Special:EntityData/{Q}.json to read
   sitelinks for cs/en wikis.
2. For the first preferred language that has a sitelink, hit Wikipedia's
   REST v1 summary endpoint /api/rest_v1/page/summary/{title}.

Both endpoints support cache-friendly GET, no API key required.

Failure modes (all silent — caller may simply skip enrichment):
- No QID → return None.
- No sitelink for any preferred lang → return None.
- HTTP / parse error → return None, log warning.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from app.cache.base import BaseCache
from app.core.logging import get_logger
from app.providers.base import BaseProvider, ProviderError

logger = get_logger(__name__)


PREFERRED_LANGS = ("cs", "en")
ENTITY_DATA_URL = "https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"
SUMMARY_URL = "https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title}"


class WikipediaProvider(BaseProvider):
    def __init__(self, cache: BaseCache) -> None:
        super().__init__(cache)

    @property
    def name(self) -> str:
        return "wikipedia"

    @property
    def ttl_seconds(self) -> int:
        # Article summaries change rarely; week-long TTL is plenty.
        return 7 * 24 * 3600

    def cache_key(self, params: dict[str, Any]) -> str:
        return self._make_cache_key("wikipedia", params)

    async def _fetch_live(self, params: dict[str, Any]) -> Any:
        op = params.get("op")
        if op == "entity":
            url = ENTITY_DATA_URL.format(qid=params["qid"])
            return await self._http_get(url, timeout=15.0, retries=2)
        if op == "summary":
            url = SUMMARY_URL.format(
                lang=params["lang"], title=quote(params["title"], safe="")
            )
            return await self._http_get(url, timeout=15.0, retries=2)
        raise ProviderError(self.name, f"Unknown op: {op}")

    # ── Public API ───────────────────────────────────────────────────────

    async def fetch_summary(self, wikidata_id: str) -> dict[str, str] | None:
        """Resolve a Wikidata QID to a Wikipedia summary.

        Returns a dict ``{summary, url, lang}`` on success, or ``None`` if
        no usable article exists.  Errors are swallowed and logged so the
        caller can simply skip the stop on failure.
        """
        if not wikidata_id:
            return None

        try:
            entity_payload = await self.fetch({"op": "entity", "qid": wikidata_id})
        except ProviderError as e:
            logger.warning("wikipedia_entity_failed", qid=wikidata_id, reason=str(e))
            return None

        sitelinks = (
            (entity_payload or {})
            .get("entities", {})
            .get(wikidata_id, {})
            .get("sitelinks", {})
        )

        for lang in PREFERRED_LANGS:
            site_key = f"{lang}wiki"
            site = sitelinks.get(site_key)
            if not site or not site.get("title"):
                continue
            title = site["title"]
            try:
                payload = await self.fetch(
                    {"op": "summary", "lang": lang, "title": title}
                )
            except ProviderError as e:
                logger.warning(
                    "wikipedia_summary_failed",
                    qid=wikidata_id,
                    lang=lang,
                    title=title,
                    reason=str(e),
                )
                continue

            extract = (payload or {}).get("extract") or ""
            if not extract.strip():
                continue
            url = (
                ((payload or {}).get("content_urls") or {})
                .get("desktop", {})
                .get("page")
                or site.get("url")
                or f"https://{lang}.wikipedia.org/wiki/{quote(title)}"
            )
            return {"summary": extract.strip(), "url": url, "lang": lang}

        return None
