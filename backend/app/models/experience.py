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


class ExperienceStop(BaseModel):
    id: str
    order: int

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


class GenerationMetadata(BaseModel):
    started_at: datetime
    completed_at: datetime | None = None
    pipeline_steps: list[str] = Field(default_factory=list)
    provider_calls: dict[str, int] = Field(default_factory=dict)
    cache_hits: dict[str, int] = Field(default_factory=dict)
    total_candidates_evaluated: int = 0


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

    error_code: str | None = None
    error_message: str | None = None
