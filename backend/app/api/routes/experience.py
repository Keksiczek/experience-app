from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from app.api.routes.gpx import build_gpx
from app.jobs.experience_job import (
    create_job,
    delete_job,
    get_experience_async,
    list_job_ids,
    run_experience_job,
)
from app.models.experience import Experience, ExperienceSummary

router = APIRouter(prefix="/experiences", tags=["experiences"])


class CreateExperienceRequest(BaseModel):
    prompt: str


class CreateExperienceResponse(BaseModel):
    job_id: str
    status: str


@router.get("", response_model=list[ExperienceSummary])
async def list_experiences(
    limit: int = Query(default=20, ge=1, le=100),
) -> list[ExperienceSummary]:
    """List recent experiences (newest first) as lightweight summaries."""
    ids = await list_job_ids()
    summaries: list[ExperienceSummary] = []
    for job_id in ids[:limit]:
        exp = await get_experience_async(job_id)
        if exp is not None:
            summaries.append(ExperienceSummary.from_experience(exp))
    return summaries


@router.post("", response_model=CreateExperienceResponse, status_code=202)
async def create_experience(
    body: CreateExperienceRequest,
    background_tasks: BackgroundTasks,
) -> CreateExperienceResponse:
    if not body.prompt or not body.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt nesmí být prázdný")
    if len(body.prompt) > 2000:
        raise HTTPException(status_code=400, detail="Prompt je příliš dlouhý (max 2000 znaků)")

    experience = await create_job(body.prompt)
    background_tasks.add_task(run_experience_job, experience)

    return CreateExperienceResponse(job_id=experience.id, status="pending")


@router.get("/{job_id}", response_model=Experience)
async def get_experience_by_id(job_id: str) -> Experience:
    experience = await get_experience_async(job_id)
    if experience is None:
        raise HTTPException(status_code=404, detail=f"Experience '{job_id}' nenalezena")
    return experience


@router.delete("/{job_id}", status_code=204)
async def delete_experience(job_id: str) -> Response:
    deleted = await delete_job(job_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Experience '{job_id}' nenalezena")
    return Response(status_code=204)


@router.get(
    "/{job_id}/gpx",
    responses={200: {"content": {"application/gpx+xml": {}}}},
)
async def get_experience_gpx(job_id: str) -> Response:
    experience = await get_experience_async(job_id)
    if experience is None:
        raise HTTPException(status_code=404, detail=f"Experience '{job_id}' nenalezena")
    has_geo = any(
        s.lat is not None and s.lon is not None for s in experience.stops
    )
    if not has_geo:
        raise HTTPException(
            status_code=409,
            detail="Experience nemá žádnou zastávku se souřadnicemi.",
        )
    gpx_xml = build_gpx(experience)
    filename = f"experience-{job_id[:8]}.gpx"
    return Response(
        content=gpx_xml,
        media_type="application/gpx+xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
