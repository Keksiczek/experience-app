import asyncio
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from app.jobs.experience_job import get_experience, run_experience_job
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

    # Start pipeline job — in-memory, async
    job_id = str(__import__("uuid").uuid4())

    from app.models.experience import JobStatus
    from app.jobs.experience_job import _jobs, Experience
    from app.models.experience import Experience as Exp
    exp = Exp(id=job_id, prompt=body.prompt, job_status=JobStatus.PENDING)
    _jobs[job_id] = exp

    background_tasks.add_task(_run_job, job_id, body.prompt)

    return CreateExperienceResponse(job_id=job_id, status="pending")


async def _run_job(job_id: str, prompt: str) -> None:
    from app.jobs.experience_job import _jobs, _execute_pipeline
    experience = _jobs.get(job_id)
    if experience:
        await _execute_pipeline(experience, prompt)


@router.get("/{job_id}", response_model=Experience)
async def get_experience_by_id(job_id: str) -> Experience:
    experience = get_experience(job_id)
    if experience is None:
        raise HTTPException(status_code=404, detail=f"Experience '{job_id}' nenalezena")
    return experience
