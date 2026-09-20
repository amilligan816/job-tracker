import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.crud import apply_updates, get_or_404
from app.db import get_db
from app.models import (
    Application,
    ApplicationEvent,
    ApplicationStatus,
    EventKind,
    JobPosting,
)
from app.schemas import (
    ApplicationCreate,
    ApplicationDetail,
    ApplicationEventCreate,
    ApplicationEventRead,
    ApplicationRead,
    ApplicationUpdate,
    PipelineSummary,
)

router = APIRouter(prefix="/applications", tags=["applications"])

_LIST_OPTS = (selectinload(Application.posting).selectinload(JobPosting.company),)
_DETAIL_OPTS = (
    selectinload(Application.posting).selectinload(JobPosting.company),
    selectinload(Application.events),
    selectinload(Application.documents),
)


@router.get("", response_model=list[ApplicationRead])
async def list_applications(
    db: AsyncSession = Depends(get_db),
    status_filter: list[ApplicationStatus] | None = Query(default=None, alias="status"),
    company_id: uuid.UUID | None = None,
    due_before: date | None = Query(
        default=None, description="Only applications whose next action falls on or before this date"
    ),
    limit: int = Query(default=200, le=1000),
    offset: int = 0,
):
    stmt = (
        select(Application)
        .options(*_LIST_OPTS)
        .order_by(
            # Anything with a due date first, soonest first; then newest.
            Application.next_action_on.asc().nullslast(),
            Application.created_at.desc(),
        )
    )
    if status_filter:
        stmt = stmt.where(Application.status.in_(status_filter))
    if company_id:
        stmt = stmt.join(JobPosting).where(JobPosting.company_id == company_id)
    if due_before:
        stmt = stmt.where(Application.next_action_on <= due_before)

    result = await db.execute(stmt.limit(limit).offset(offset))
    return result.scalars().all()


@router.get("/summary", response_model=PipelineSummary)
async def pipeline_summary(db: AsyncSession = Depends(get_db)):
    """Counts per status, for the dashboard."""
    result = await db.execute(
        select(Application.status, func.count(Application.id)).group_by(Application.status)
    )
    by_status = {status_value.value: count for status_value, count in result.all()}

    overdue = await db.execute(
        select(func.count(Application.id)).where(Application.next_action_on <= date.today())
    )
    return PipelineSummary(
        by_status=by_status,
        total=sum(by_status.values()),
        needs_action=overdue.scalar_one(),
    )


@router.post("", response_model=ApplicationDetail, status_code=status.HTTP_201_CREATED)
async def create_application(payload: ApplicationCreate, db: AsyncSession = Depends(get_db)):
    await get_or_404(db, JobPosting, payload.posting_id)
    application = Application(**payload.model_dump())
    db.add(application)
    await db.flush()

    db.add(
        ApplicationEvent(
            application_id=application.id,
            kind=EventKind.status_change,
            summary=f"Tracked as {application.status.value}",
        )
    )
    await db.flush()
    return await _reload(db, application.id)


@router.get("/{application_id}", response_model=ApplicationDetail)
async def get_application(application_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    await get_or_404(db, Application, application_id)
    return await _reload(db, application_id)


@router.patch("/{application_id}", response_model=ApplicationDetail)
async def update_application(
    application_id: uuid.UUID, payload: ApplicationUpdate, db: AsyncSession = Depends(get_db)
):
    application = await get_or_404(db, Application, application_id)
    previous_status = application.status

    apply_updates(application, payload)

    # A status move is the thing worth a timeline entry; other edits are not.
    if application.status != previous_status:
        db.add(
            ApplicationEvent(
                application_id=application.id,
                kind=EventKind.status_change,
                summary=f"{previous_status.value} -> {application.status.value}",
            )
        )
        if application.status == ApplicationStatus.applied and application.applied_on is None:
            application.applied_on = date.today()

    await db.flush()
    return await _reload(db, application_id)


@router.delete("/{application_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_application(application_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    application = await get_or_404(db, Application, application_id)
    await db.delete(application)


# ---------------------------------------------------------------------------- events


@router.get("/{application_id}/events", response_model=list[ApplicationEventRead])
async def list_events(application_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    await get_or_404(db, Application, application_id)
    result = await db.execute(
        select(ApplicationEvent)
        .where(ApplicationEvent.application_id == application_id)
        .order_by(ApplicationEvent.occurred_at.desc())
    )
    return result.scalars().all()


@router.post(
    "/{application_id}/events",
    response_model=ApplicationEventRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_event(
    application_id: uuid.UUID,
    payload: ApplicationEventCreate,
    db: AsyncSession = Depends(get_db),
):
    await get_or_404(db, Application, application_id)
    event = ApplicationEvent(
        application_id=application_id,
        kind=payload.kind,
        summary=payload.summary,
        detail=payload.detail,
    )
    if payload.occurred_at:
        event.occurred_at = payload.occurred_at
    db.add(event)
    await db.flush()
    await db.refresh(event)
    return event


async def _reload(db: AsyncSession, application_id: uuid.UUID) -> Application | None:
    result = await db.execute(
        select(Application).options(*_DETAIL_OPTS).where(Application.id == application_id)
    )
    return result.scalar_one_or_none()
