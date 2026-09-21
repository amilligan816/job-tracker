import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.db import SessionLocal
from app.llm import AssistantUnavailable
from app.mail import sync as mail_sync
from app.routers import (
    applications,
    assistant,
    companies,
    documents,
    experience,
    mail,
    postings,
    resumes,
)
from app.storage import ensure_bucket

settings = get_settings()
logging.basicConfig(level=settings.log_level.upper())
logger = logging.getLogger(__name__)


async def _mail_sync_loop(interval: int) -> None:
    """Poll connected mailboxes in the background.

    Polling rather than Gmail push: push needs a Pub/Sub topic and a publicly
    reachable endpoint, which a locally-run stack does not have. The loop sleeps
    first so a restart loop can't turn into a burst of syncs.
    """
    while True:
        await asyncio.sleep(interval)
        try:
            async with SessionLocal() as session:
                await mail_sync.sync_all(session)
                await session.commit()
        except asyncio.CancelledError:
            raise
        except Exception:
            # A failed run is recorded on the account; the loop keeps its cadence.
            logger.exception("Scheduled mail sync failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await ensure_bucket()
    except Exception:
        # Storage being down shouldn't stop the API from serving CRUD; the
        # document routes will surface the failure when they're actually used.
        logger.warning("Could not verify the object storage bucket at startup", exc_info=True)

    sync_task = None
    interval = settings.mail_sync_interval_seconds
    if settings.gmail_configured and interval > 0:
        logger.info("Polling connected mailboxes every %ss", interval)
        sync_task = asyncio.create_task(_mail_sync_loop(interval))

    yield

    if sync_task:
        sync_task.cancel()
        with suppress(asyncio.CancelledError):
            await sync_task


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
    return {
        "status": "ok",
        "assistant_enabled": settings.assistant_enabled,
        "mail_enabled": settings.gmail_configured,
    }


for router in (
    companies.router,
    postings.router,
    applications.router,
    documents.router,
    experience.router,
    resumes.router,
    assistant.router,
    mail.router,
):
    app.include_router(router, prefix="/api")
