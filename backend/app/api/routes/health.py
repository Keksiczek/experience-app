import httpx
from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import settings

router = APIRouter(tags=["health"])


class ProviderStatus(BaseModel):
    mapillary: str
    nominatim: str
    overpass: str
    wikimedia: str
    wikidata: str
    ollama: str


class HealthResponse(BaseModel):
    status: str
    providers: ProviderStatus
    ollama_model: str | None = None


async def _probe_ollama() -> str:
    """Return 'ok', 'unavailable', or 'disabled' for the Ollama provider."""
    if not settings.ollama_enabled:
        return "disabled"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.ollama_base_url}/api/tags")
            resp.raise_for_status()
            data = resp.json()
        models = [m.get("name", "") for m in data.get("models", [])]
        if any(settings.ollama_model in m for m in models):
            return "ok"
        return "unavailable"
    except Exception:
        return "unavailable"


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    mapillary_status = "configured" if settings.mapillary_api_key else "no_api_key"
    ollama_status = await _probe_ollama()

    return HealthResponse(
        status="ok",
        providers=ProviderStatus(
            mapillary=mapillary_status,
            nominatim="available",
            overpass="available",
            wikimedia="available",
            wikidata="available",
            ollama=ollama_status,
        ),
        ollama_model=settings.ollama_model if settings.ollama_enabled else None,
    )
