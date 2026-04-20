from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI

from app.api.routes.experience import router as experience_router
from app.api.routes.health import router as health_router
from app.core.config import settings
from app.core.logging import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    configure_logging(settings.log_level)
    yield


app = FastAPI(
    title="Experience App",
    description="Kurátorované geo-exploration experiences z reálných open dat.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(experience_router)
