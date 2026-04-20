from pydantic import BaseModel, Field


class RegionCandidate(BaseModel):
    name: str
    lat_min: float
    lon_min: float
    lat_max: float
    lon_max: float
    source: str                    # "nominatim" | "static_fallback"
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)


class ScoreBreakdown(BaseModel):
    prompt_relevance: float = 0.0
    media_availability: float = 0.0
    scenic_value: float = 0.0
    diversity_bonus: float = 0.0
    route_coherence: float = 0.0


class PlaceCandidate(BaseModel):
    id: str                        # e.g. "osm:node:123456"
    lat: float
    lon: float
    name: str
    source_type: str               # "osm" | "wikidata"
    tags: dict[str, str] = Field(default_factory=dict)
    region_id: str = ""

    # Scores (populated after scoring step)
    prompt_relevance_score: float = 0.0
    scenic_score: float = 0.0
    context_score: float = 0.0
    final_score: float = 0.0
    score_breakdown: ScoreBreakdown = Field(default_factory=ScoreBreakdown)
