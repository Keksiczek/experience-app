from enum import Enum
from pydantic import BaseModel, Field


class ExperienceMode(str, Enum):
    SCENIC_ROADTRIP = "scenic_roadtrip"
    REMOTE_LANDSCAPE = "remote_landscape"
    ABANDONED_INDUSTRIAL = "abandoned_industrial"


class PromptIntent(BaseModel):
    original_prompt: str

    mode: ExperienceMode

    # Semantic categories derived from prompt
    themes: list[str] = Field(default_factory=list)
    terrain: list[str] = Field(default_factory=list)
    mood: list[str] = Field(default_factory=list)
    infrastructure: list[str] = Field(default_factory=list)
    climate: list[str] = Field(default_factory=list)
    travel_mode: list[str] = Field(default_factory=list)

    # Geographic preferences
    preferred_regions: list[str] = Field(default_factory=list)
    excluded_regions: list[str] = Field(default_factory=list)

    # Place characteristics
    settlement_density: str = "any"        # "none" | "sparse" | "any"

    # Route characteristics
    route_style: str = "scattered"         # "linear" | "loop" | "scattered"
    estimated_stops: int = 5

    # Parser metadata
    confidence: float = Field(ge=0.0, le=1.0)
    parse_warnings: list[str] = Field(default_factory=list)
    confidence_reasons: list[str] = Field(default_factory=list)
    ambiguity_signals: list[str] = Field(default_factory=list)
