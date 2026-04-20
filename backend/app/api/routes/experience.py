from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from app.jobs.experience_job import create_job, get_experience_async, run_experience_job
from app.models.experience import Experience

router = APIRouter(prefix="/experiences", tags=["experiences"])


class CreateExperienceRequest(BaseModel):
    prompt: str


class CreateExperienceResponse(BaseModel):
    job_id: str
    status: str


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
