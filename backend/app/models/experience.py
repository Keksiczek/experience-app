from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field

from app.models.media import FallbackLevel


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"


class NarrationResult(BaseModel):
    why_here: str
    narration: str
    confidence: float
    sources_used: list[str] = []
    used_llm: bool = False
    fallback_reason: str | None = None


class ExperienceStop(BaseModel):
    id: str
    order: int
    stop_order: int = 0   # 0-indexed final display order after route coherence

    place_id: str
    media_id: str | None = None

    lat: float
    lon: float
    name: str

    short_title: str
    why_here: str
    narration: str

    fallback_level: FallbackLevel
    score: float = 0.0
    narration_confidence: float = 0.0   # 0.0 = bare coords only, 1.0 = rich context

    # Per-stop explainability
    decision_reasons: list[str] = Field(default_factory=list)
    fallback_reason: str | None = None
    emergency_threshold_used: bool = False

    # LLM narration metadata
    grounding_sources: list[str] = Field(default_factory=list)
    used_llm_narration: bool = False
    llm_fallback_reason: str | None = None

    # Encyclopedic enrichment (filled by WikipediaProvider after composer)
    wikipedia_summary: str | None = None   # ~1 paragraph from Wikipedia article
    wikipedia_url: str | None = None       # Direct link to the source article
    wikipedia_lang: str | None = None      # "cs" / "en" — which language was used

    # Up to a few extra image media IDs (e.g. "wikimedia:Foo.jpg") gathered
    # from the Wikipedia article body.  The primary `media_id` is kept as
    # the hero; this list backs the theater gallery.
    extra_media: list[str] = Field(default_factory=list)


class GenerationMetadata(BaseModel):
    started_at: datetime
    completed_at: datetime | None = None
    intent_mode: str | None = None  # e.g. "abandoned_industrial" — hint for client UI
    pipeline_steps: list[str] = Field(default_factory=list)
    provider_calls: dict[str, int] = Field(default_factory=dict)
    cache_hits: dict[str, int] = Field(default_factory=dict)
    total_candidates_evaluated: int = 0

    # Pipeline explainability
    warnings: list[str] = Field(default_factory=list)
    decision_reasons: list[str] = Field(default_factory=list)
    degradation_reason: str | None = None

    # Route coherence
    route_coherence_applied: bool = False
    route_style_used: str | None = None

    # LLM narration stats
    llm_narration_used: bool = False
    llm_narration_model: str | None = None
    llm_fallback_count: int = 0


class ExperienceQualityMetrics(BaseModel):
    """Whole-experience quality signal. All values 0.0–1.0 unless noted."""

    # Ratio of stops that have any media (Mapillary or Wikimedia)
    imagery_coverage_ratio: float = 0.0

    # Count of stops per FallbackLevel, e.g. {"FULL": 3, "NO_MEDIA": 2}
    fallback_distribution: dict[str, int] = Field(default_factory=dict)

    # Average pairwise haversine distance between stops / pipeline_max_diversity_km
    # 0 = all stops clustered, 1 = maximally spread
    diversity_score: float = 0.0

    # How well stops follow the intended route_style geometry (0 = poor, 1 = ideal)
    route_coherence_score: float = 0.0

    # Average narration_confidence across all stops
    narration_confidence: float = 0.0

    # Average number of meaningful OSM tags per stop, normalised to 0–1 (cap at 8 tags)
    context_richness: float = 0.0


class Experience(BaseModel):
    id: str
    job_status: JobStatus = JobStatus.PENDING

    prompt: str
    selected_region: str = ""

    stops: list[ExperienceStop] = Field(default_factory=list)
    summary: str = ""

    quality_flags: list[str] = Field(default_factory=list)
    quality_metrics: ExperienceQualityMetrics | None = None
    generation_metadata: GenerationMetadata | None = None

    created_at: datetime | None = None

    error_code: str | None = None
    error_message: str | None = None


class ExperienceSummary(BaseModel):
    job_id: str
    job_status: JobStatus
    prompt: str
    stop_count: int
    quality_flags: list[str]
    created_at: datetime | None
    error_code: str | None = None

    @classmethod
    def from_experience(cls, exp: "Experience") -> "ExperienceSummary":
        return cls(
            job_id=exp.id,
            job_status=exp.job_status,
            prompt=exp.prompt,
            stop_count=len(exp.stops),
            quality_flags=exp.quality_flags,
            created_at=exp.created_at,
            error_code=exp.error_code,
        )
