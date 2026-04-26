"""Curated sample experiences served read-only from disk.

Samples live in ``data/samples/curated/*.json`` (relative to repo root).  Each
file is a serialised :class:`Experience` produced by running the mock pipeline,
extended with a few extra fields the API surfaces but the model doesn't:

* ``slug``     — stable URL identifier (filename without extension)
* ``cover_image`` (optional) — direct image URL to use as the discovery card
* ``teaser`` (optional)      — short marketing copy shown on the home page

The samples never live in the job store, so they can't be deleted via
``DELETE /experiences/{id}``.  Listing returns the lightweight summaries
ordered by ``order`` field (or filename order when not present).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from app.api.routes.gpx import build_gpx
from app.core.logging import get_logger
from app.models.experience import Experience

logger = get_logger(__name__)

# repo_root/data/samples/curated/
_SAMPLES_DIR = Path(__file__).resolve().parents[4] / "data" / "samples" / "curated"

router = APIRouter(prefix="/samples", tags=["samples"])


class SampleSummary(BaseModel):
    slug: str
    title: str
    teaser: str | None = None
    cover_image: str | None = None
    region: str | None = None
    stop_count: int = 0


def _load_one(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:  # noqa: BLE001
        logger.warning("sample_load_failed", path=str(path), error=str(e))
        return None


def _list_files() -> list[Path]:
    if not _SAMPLES_DIR.exists():
        return []
    return sorted(_SAMPLES_DIR.glob("*.json"))


@router.get("", response_model=list[SampleSummary])
async def list_samples() -> list[SampleSummary]:
    out: list[SampleSummary] = []
    for path in _list_files():
        raw = _load_one(path)
        if raw is None:
            continue
        slug = raw.get("slug") or path.stem
        title = raw.get("title") or raw.get("prompt") or slug
        out.append(
            SampleSummary(
                slug=slug,
                title=title,
                teaser=raw.get("teaser"),
                cover_image=raw.get("cover_image"),
                region=raw.get("selected_region"),
                stop_count=len(raw.get("stops") or []),
            )
        )
    # Optional explicit ordering via "order" field, then by title.
    out.sort(key=lambda s: (s.title, s.slug))
    return out


def _load_sample_experience(slug: str) -> Experience:
    safe = slug.replace("/", "").replace("..", "")
    path = _SAMPLES_DIR / f"{safe}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Sample '{slug}' nenalezen")
    raw = _load_one(path)
    if raw is None:
        raise HTTPException(status_code=500, detail="Nelze načíst sample.")
    # Strip curator-only fields before validating against the strict
    # Experience schema — the model rejects unknown extras.
    for k in ("slug", "title", "teaser", "cover_image"):
        raw.pop(k, None)
    return Experience.model_validate(raw)


@router.get("/{slug}", response_model=Experience)
async def get_sample(slug: str) -> Experience:
    return _load_sample_experience(slug)


@router.get(
    "/{slug}/gpx",
    responses={200: {"content": {"application/gpx+xml": {}}}},
)
async def get_sample_gpx(slug: str) -> Response:
    experience = _load_sample_experience(slug)
    has_geo = any(
        s.lat is not None and s.lon is not None for s in experience.stops
    )
    if not has_geo:
        raise HTTPException(
            status_code=409,
            detail="Sample nemá žádnou zastávku se souřadnicemi.",
        )
    gpx_xml = build_gpx(experience)
    filename = f"sample-{slug}.gpx"
    return Response(
        content=gpx_xml,
        media_type="application/gpx+xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
