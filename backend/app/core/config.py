from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ScoringWeights(BaseSettings):
    prompt_relevance: float = 0.35
    media_availability: float = 0.25
    scenic_value: float = 0.15
    diversity_bonus: float = 0.15
    route_coherence: float = 0.10

    @model_validator(mode="after")
    def weights_sum_to_one(self) -> "ScoringWeights":
        total = (
            self.prompt_relevance
            + self.media_availability
            + self.scenic_value
            + self.diversity_bonus
            + self.route_coherence
        )
        if abs(total - 1.0) > 0.001:
            raise ValueError(f"Scoring weights must sum to 1.0, got {total:.3f}")
        return self


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # API keys
    mapillary_api_key: str = ""

    # Cache
    cache_dir: str = "./data/caches"
    cache_ttl_nominatim: int = 604_800   # 7 days
    cache_ttl_overpass: int = 86_400     # 24 hours
    cache_ttl_wikidata: int = 172_800    # 48 hours
    cache_ttl_wikimedia: int = 86_400    # 24 hours
    cache_ttl_mapillary: int = 21_600    # 6 hours

    # ── Quality gates ─────────────────────────────────────────────────────────
    #
    # Place count gates
    pipeline_min_places: int = 3        # ABORT if fewer than this survive scoring
    pipeline_ideal_places: int = 8      # WARNING + shorter experience if fewer
    #
    # Experience length (stops selected by composer)
    pipeline_stops_target: int = 6      # Ideal experience length
    pipeline_stops_min: int = 3         # Minimum viable; below this = failed experience
    #
    # Scoring thresholds
    pipeline_score_threshold: float = 0.40       # Normal threshold for stop inclusion
    pipeline_score_threshold_emergency: float = 0.25  # Used when no stop reaches normal threshold;
    #                                                    triggers quality_flag "emergency_threshold"
    #
    # Media quality gate
    pipeline_media_low_threshold: float = 0.50   # Fraction of stops WITHOUT media above which
    #                                               quality_flag "low_media" is set
    #
    # Narration quality gate
    pipeline_narration_min_tags: int = 2         # Minimum meaningful OSM tags for a full narration;
    #                                               below this → short factual note only
    pipeline_narration_weak_threshold: float = 0.50  # narration_confidence below this = weak stop;
    #                                                   quality_flag "partial_narration" if majority
    #
    # Diversity / route geometry
    pipeline_min_diversity_km: float = 15.0      # Stops closer than this are penalised for diversity
    pipeline_max_diversity_km: float = 100.0     # Beyond this, diversity bonus is capped (not linear)
    #
    # Provider search radii
    pipeline_mapillary_radius_m: int = 500
    pipeline_wikimedia_radius_m: int = 1000
    # ─────────────────────────────────────────────────────────────────────────

    # Mock mode — runs pipeline on sample data without any live API calls
    mock_mode: bool = False

    # Job store
    job_store_path: str = "./data/jobs.db"
    job_store_ttl_days: int = 7

    # Logging
    log_level: str = "INFO"

    # Scoring weights
    scoring: ScoringWeights = ScoringWeights()

    @field_validator("mapillary_api_key")
    @classmethod
    def warn_missing_mapillary_key(cls, v: str) -> str:
        if not v:
            import warnings
            warnings.warn(
                "MAPILLARY_API_KEY not set — Mapillary provider will be skipped",
                stacklevel=2,
            )
        return v


settings = Settings()
