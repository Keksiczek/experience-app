from enum import Enum
from pydantic import BaseModel


class MediaProvider(str, Enum):
    MAPILLARY = "mapillary"
    WIKIMEDIA = "wikimedia"


class MediaType(str, Enum):
    PHOTO = "photo"
    STREET_LEVEL = "street_level"


class FallbackLevel(str, Enum):
    FULL = "FULL"                    # Mapillary + Wikidata context
    PARTIAL_MEDIA = "PARTIAL_MEDIA"  # Wikimedia instead of Mapillary
    NO_MEDIA = "NO_MEDIA"            # No media, OSM data only
    LOW_CONTEXT = "LOW_CONTEXT"      # No Wikidata metadata
    MINIMAL = "MINIMAL"              # Only lat/lon and basic OSM tags


class MediaCandidate(BaseModel):
    id: str
    place_id: str

    provider: MediaProvider
    media_type: MediaType
    preview_url: str
    viewer_ref: str = ""             # Mapillary sequence key or Commons page

    license: str = ""
    attribution: str = ""

    coverage_score: float = 0.0     # 0.0–1.0, density of coverage around place
    confidence: float = 0.0         # 0.0–1.0, how likely this image is relevant

    distance_m: float = 0.0         # distance from place to media location
