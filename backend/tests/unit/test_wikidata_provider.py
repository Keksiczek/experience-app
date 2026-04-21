"""Unit tests for WikidataProvider.

Tests use pytest-httpx to mock HTTP without live network calls.
The rate-limit global is reset before each test to avoid inter-test sleeps.
"""

import pytest
import app.providers.wikidata as _wikidata_mod
from app.cache.base import BaseCache
from app.providers.wikidata import WikidataProvider, _parse_geo_bindings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _NullCache(BaseCache):
    """Cache that never hits — forces live fetch every time."""
    async def get(self, key: str):
        return None

    async def set(self, key: str, value, ttl: int) -> None:
        pass

    async def delete(self, key: str) -> None:
        pass

    async def clear_expired(self) -> int:
        return 0


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Reset module-level rate-limit timestamp so tests don't sleep."""
    _wikidata_mod._LAST_SPARQL_TIME = 0.0


# ---------------------------------------------------------------------------
# Sample SPARQL / search API responses
# ---------------------------------------------------------------------------

_SPARQL_RESULT_WITH_DATA = {
    "results": {
        "bindings": [
            {
                "item": {"type": "uri", "value": "http://www.wikidata.org/entity/Q12345"},
                "itemLabel": {"type": "literal", "value": "Důl Anna", "xml:lang": "cs"},
                "itemDescription": {"type": "literal", "value": "opuštěný uhelný důl"},
                "instanceLabel": {"type": "literal", "value": "coal mine"},
                "sitelinks": {"type": "literal", "value": "22"},
                "heritage": {"type": "uri", "value": "http://www.wikidata.org/entity/Q811165"},
            },
            {
                "item": {"type": "uri", "value": "http://www.wikidata.org/entity/Q12345"},
                "itemLabel": {"type": "literal", "value": "Důl Anna", "xml:lang": "cs"},
                "itemDescription": {"type": "literal", "value": "opuštěný uhelný důl"},
                "instanceLabel": {"type": "literal", "value": "industrial building"},
                "sitelinks": {"type": "literal", "value": "22"},
                "heritage": {"type": "uri", "value": "http://www.wikidata.org/entity/Q811165"},
            },
        ]
    }
}

_SPARQL_RESULT_EMPTY = {"results": {"bindings": []}}

_SEARCH_RESULT = {
    "search": [
        {
            "id": "Q67890",
            "label": "Důl Hedvika",
            "description": "historická šachta",
        }
    ]
}


# ---------------------------------------------------------------------------
# Test 1: SPARQL query construction and response parsing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sparql_construction_and_response_parsing(httpx_mock):
    """SPARQL geosearch returns valid bindings → WikidataContext parsed correctly.

    Responses are added without URL filter so they match any request in order.
    """
    httpx_mock.add_response(json=_SPARQL_RESULT_WITH_DATA)

    provider = WikidataProvider(_NullCache())
    result = await provider.fetch_context_for_place("osm:node:111", 50.0, 18.0)

    assert result is not None
    assert result.wikidata_id == "Q12345"
    assert result.description == "opuštěný uhelný důl"
    assert "coal mine" in result.instance_of
    assert "industrial building" in result.instance_of
    assert result.heritage_status == "listed"
    assert result.tourism_score == pytest.approx(22 / 50)
    assert result.raw_labels.get("cs") == "Důl Anna"


# ---------------------------------------------------------------------------
# Test 2: fallback to search API when SPARQL returns empty
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fallback_to_search_when_sparql_empty(httpx_mock):
    """Empty SPARQL bindings with a name → falls back to wbsearchentities.

    Two responses registered in order: first is SPARQL (empty), second is search API.
    """
    httpx_mock.add_response(json=_SPARQL_RESULT_EMPTY)   # 1st request: SPARQL
    httpx_mock.add_response(json=_SEARCH_RESULT)          # 2nd request: search API

    provider = WikidataProvider(_NullCache())
    result = await provider.fetch_context_for_place(
        "osm:node:222", 50.1, 18.1, name="Důl Hedvika"
    )

    assert result is not None
    assert result.wikidata_id == "Q67890"
    assert result.description == "historická šachta"
    # Search API fallback result has no heritage or tourism data
    assert result.heritage_status is None
    assert result.tourism_score == 0.0


# ---------------------------------------------------------------------------
# Test 3: graceful degradation on HTTP 500
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_graceful_degradation_on_http_500(httpx_mock):
    """HTTP 500 from Wikidata SPARQL → provider returns None, never raises."""
    httpx_mock.add_response(status_code=500)

    provider = WikidataProvider(_NullCache())
    # No name → no fallback search attempted; single HTTP call returns 500
    result = await provider.fetch_context_for_place("osm:node:333", 50.2, 18.2)

    assert result is None   # graceful degradation, not an exception


# ---------------------------------------------------------------------------
# Unit tests for _parse_geo_bindings (pure function, no HTTP)
# ---------------------------------------------------------------------------

def test_parse_geo_bindings_empty():
    assert _parse_geo_bindings([]) is None


def test_parse_geo_bindings_picks_highest_sitelinks():
    bindings = [
        {
            "item": {"type": "uri", "value": "http://www.wikidata.org/entity/Q1"},
            "itemLabel": {"type": "literal", "value": "First"},
            "sitelinks": {"type": "literal", "value": "5"},
        },
        {
            "item": {"type": "uri", "value": "http://www.wikidata.org/entity/Q2"},
            "itemLabel": {"type": "literal", "value": "Second"},
            "sitelinks": {"type": "literal", "value": "30"},
        },
    ]
    result = _parse_geo_bindings(bindings)
    assert result is not None
    assert result.wikidata_id == "Q2"
    assert result.tourism_score == pytest.approx(30 / 50)


def test_parse_geo_bindings_tourism_score_capped_at_1():
    bindings = [
        {
            "item": {"type": "uri", "value": "http://www.wikidata.org/entity/Q3"},
            "itemLabel": {"type": "literal", "value": "Famous"},
            "sitelinks": {"type": "literal", "value": "200"},
        },
    ]
    result = _parse_geo_bindings(bindings)
    assert result is not None
    assert result.tourism_score == 1.0


def test_parse_geo_bindings_no_heritage_when_field_absent():
    bindings = [
        {
            "item": {"type": "uri", "value": "http://www.wikidata.org/entity/Q4"},
            "itemLabel": {"type": "literal", "value": "Unlisted"},
            "sitelinks": {"type": "literal", "value": "3"},
            # no "heritage" key
        },
    ]
    result = _parse_geo_bindings(bindings)
    assert result is not None
    assert result.heritage_status is None
