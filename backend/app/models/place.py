from pydantic import BaseModel, Field


class WikidataContext(BaseModel):
    wikidata_id: str | None = None
    description: str | None = None        # short description (cs or en)
    instance_of: list[str] = []           # ["coal mine", "factory", ...]
    heritage_status: str | None = None    # "listed", "UNESCO", None
    image_url: str | None = None
    tourism_score: float = 0.0            # 0.0–1.0 derived from sitelinks count
    raw_labels: dict[str, str] = {}       # {"cs": "...", "en": "..."}


class RegionCandidate(BaseModel):
    region_id: str = ""
    name: str
    lat_min: float
    lon_min: float
    lat_max: float
    lon_max: float
    source: str                    # "nominatim" | "registry" | "static_fallback"
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    country: str = ""
    supported_modes: list[str] = Field(default_factory=list)
    expected_media_coverage: str = "unknown"   # "high" | "medium" | "low" | "unknown"
    known_limitations: list[str] = Field(default_factory=list)
    decision_reasons: list[str] = Field(default_factory=list)


class ScoreBreakdown(BaseModel):
    prompt_relevance: float = 0.0
    media_availability: float = 0.0
    scenic_value: float = 0.0
    diversity_bonus: float = 0.0
    route_coherence: float = 0.0
    context_richness: float = 0.0
    context_score: float = 0.0        # Wikidata-derived bonus (heritage/tourism/description)
    similarity_penalty: float = 0.0   # how much was deducted
    combo_bonus: float = 0.0
    decision_reasons: list[str] = Field(default_factory=list)


class PlaceCandidate(BaseModel):
    id: str                        # e.g. "osm:node:123456"
    lat: float
    lon: float
    name: str
    source_type: str               # "osm" | "wikidata"
    tags: dict[str, str] = Field(default_factory=dict)
    region_id: str = ""

    # Signal tier from discovery (set by OSM provider)
    signal_strength: str = "weak"  # "must_have" | "strong" | "weak"
    discovery_warnings: list[str] = Field(default_factory=list)

    # Wikidata enrichment (populated after place discovery)
    wikidata: WikidataContext | None = None

    # Scores (populated after scoring step)
    prompt_relevance_score: float = 0.0
    scenic_score: float = 0.0
    context_score: float = 0.0
    final_score: float = 0.0
    score_breakdown: ScoreBreakdown = Field(default_factory=ScoreBreakdown)
