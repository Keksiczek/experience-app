"""Wikipedia REST summary provider.

Given a Wikidata QID, fetches a 1-paragraph summary from the corresponding
Wikipedia article (preferring Czech, falling back to English) plus a small
gallery of related media files from the article body.

Implementation:
1. Fetch the Wikidata entity JSON via Special:EntityData/{Q}.json to read
   sitelinks for cs/en wikis.
2. For the first preferred language that has a sitelink, hit Wikipedia's
   REST v1 summary endpoint /api/rest_v1/page/summary/{title}.
3. Optionally call /api/rest_v1/page/media-list/{title} to gather up to
   ``MAX_GALLERY`` extra image titles for the stop's theater gallery.

All endpoints support cache-friendly GET, no API key required.

Failure modes (all silent — caller may simply skip enrichment):
- No QID → return None.
- No sitelink for any preferred lang → return None.
- HTTP / parse error on summary → return None, log warning.
- HTTP / parse error on media-list → keep summary, return [] for media.
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
MEDIA_LIST_URL = "https://{lang}.wikipedia.org/api/rest_v1/page/media-list/{title}"
MAX_GALLERY = 6


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
        if op == "media_list":
            url = MEDIA_LIST_URL.format(
                lang=params["lang"], title=quote(params["title"], safe="")
            )
            return await self._http_get(url, timeout=15.0, retries=2)
        raise ProviderError(self.name, f"Unknown op: {op}")

    # ── Public API ───────────────────────────────────────────────────────

    async def fetch_summary(self, wikidata_id: str) -> dict[str, Any] | None:
        """Resolve a Wikidata QID to a Wikipedia summary + gallery.

        Returns a dict ``{summary, url, lang, gallery}`` on success, or
        ``None`` if no usable article exists.  ``gallery`` is a list of
        Commons file titles (without any prefix), suitable for passing
        through ``WikimediaProvider._thumb_url`` or for storing as
        ``"wikimedia:<filename>"`` on the stop.

        Errors are swallowed and logged so the caller can simply skip the
        stop on failure.
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
                summary_payload = await self.fetch(
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

            extract = (summary_payload or {}).get("extract") or ""
            if not extract.strip():
                continue
            url = (
                ((summary_payload or {}).get("content_urls") or {})
                .get("desktop", {})
                .get("page")
                or site.get("url")
                or f"https://{lang}.wikipedia.org/wiki/{quote(title)}"
            )

            gallery = await self._fetch_gallery(lang, title)

            return {
                "summary": extract.strip(),
                "url": url,
                "lang": lang,
                "gallery": gallery,
            }

        return None

    async def _fetch_gallery(self, lang: str, title: str) -> list[str]:
        """Best-effort list of image file titles attached to the article."""
        try:
            payload = await self.fetch(
                {"op": "media_list", "lang": lang, "title": title}
            )
        except ProviderError as e:
            logger.warning(
                "wikipedia_media_list_failed",
                lang=lang,
                title=title,
                reason=str(e),
            )
            return []

        items = (payload or {}).get("items", []) or []
        seen: set[str] = set()
        out: list[str] = []
        for item in items:
            if item.get("type") != "image":
                continue
            file_title = item.get("title")
            if not file_title:
                continue
            # Strip "File:" prefix; the frontend re-adds Special:FilePath.
            cleaned = file_title.removeprefix("File:").strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            out.append(cleaned)
            if len(out) >= MAX_GALLERY:
                break
        return out
