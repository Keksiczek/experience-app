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


class GenerationMetadata(BaseModel):
    started_at: datetime
    completed_at: datetime | None = None
    pipeline_steps: list[str] = Field(default_factory=list)
    provider_calls: dict[str, int] = Field(default_factory=dict)
    cache_hits: dict[str, int] = Field(default_factory=dict)
    total_candidates_evaluated: int = 0


class Experience(BaseModel):
    id: str
    job_status: JobStatus = JobStatus.PENDING

    prompt: str
    selected_region: str = ""

    stops: list[ExperienceStop] = Field(default_factory=list)
    summary: str = ""

    quality_flags: list[str] = Field(default_factory=list)
    generation_metadata: GenerationMetadata | None = None

    error_code: str | None = None
    error_message: str | None = None
