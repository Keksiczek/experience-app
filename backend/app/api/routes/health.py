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


class HealthResponse(BaseModel):
    status: str
    providers: ProviderStatus


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    mapillary_status = "configured" if settings.mapillary_api_key else "no_api_key"
    return HealthResponse(
        status="ok",
        providers=ProviderStatus(
            mapillary=mapillary_status,
            nominatim="available",
            overpass="available",
            wikimedia="available",
            wikidata="available",
        ),
    )
