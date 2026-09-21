import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.llm import AssistantUnavailable
from app.routers import (
    applications,
    assistant,
    companies,
    documents,
    experience,
    postings,
    resumes,
)
from app.storage import ensure_bucket

settings = get_settings()
logging.basicConfig(level=settings.log_level.upper())
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await ensure_bucket()
    except Exception:
        # Storage being down shouldn't stop the API from serving CRUD; the
        # document routes will surface the failure when they're actually used.
        logger.warning("Could not verify the object storage bucket at startup", exc_info=True)
    yield


app = FastAPI(
    title="Job Tracker API",
    version="0.1.0",
    summary="Track applications, store documents, and get Claude's help on both.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(AssistantUnavailable)
async def assistant_unavailable_handler(request: Request, exc: AssistantUnavailable):
    """Assistant routes degrade to 503 rather than 500 when Claude isn't usable."""
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"detail": str(exc)}
    )


@app.get("/health", tags=["meta"])
async def health():
    return {"status": "ok", "assistant_enabled": settings.assistant_enabled}


for router in (
    companies.router,
    postings.router,
    applications.router,
    documents.router,
    experience.router,
    resumes.router,
    assistant.router,
):
    app.include_router(router, prefix="/api")
