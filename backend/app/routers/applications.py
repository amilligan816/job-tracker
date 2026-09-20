import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.crud import apply_updates, get_or_404
from app.db import get_db
from app.matching import rate_match
from app.models import (
    Application,
    ApplicationEvent,
    ApplicationStatus,
    Document,
    DocumentKind,
    EventKind,
    JobPosting,
)
from app.resumes import find_resume
from app.schemas import (
    ApplicationCreate,
    ApplicationDetail,
    ApplicationEventCreate,
    ApplicationEventRead,
    ApplicationRead,
    ApplicationUpdate,
    PipelineSummary,
    PostingMatch,
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
    with_match: bool = Query(
        default=False, description="Also compute each row's deterministic match score"
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
    applications = result.scalars().all()

    if with_match:
        await _attach_match_scores(db, applications)
    return applications


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


@router.get("/{application_id}/match", response_model=PostingMatch)
async def match_rating(
    application_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    resume_document_id: uuid.UUID | None = Query(
        default=None, description="Defaults to the most relevant stored resume"
    ),
):
    """Rate this application's posting against a resume.

    Pure string matching over a skill vocabulary -- no model call, so it is free,
    instant and gives the same answer every time. A `score` of null means there
    is no resume, or the posting names too few recognisable skills to rate.
    """
    result = await db.execute(
        select(Application)
        .options(selectinload(Application.posting))
        .where(Application.id == application_id)
    )
    application = result.scalar_one_or_none()
    if application is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Application {application_id} not found"
        )

    resume = await find_resume(db, application_id, resume_document_id)
    if resume_document_id and resume is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document {resume_document_id} not found",
        )

    posting = application.posting
    rated = rate_match(
        posting_raw_text=posting.raw_text if posting else None,
        posting_extracted=posting.extracted if posting else None,
        resume_text=resume.extracted_text if resume else None,
    )
    return PostingMatch(
        score=rated.score,
        rating=rated.rating,
        confidence=rated.confidence,
        explanation=rated.explanation,
        matched=rated.matched,
        missing=rated.missing,
        extra=rated.extra,
        coverage=rated.coverage,
        required_years=rated.required_years,
        resume_years=rated.resume_years,
        years_basis=rated.years_basis,
        resume_document_id=resume.id if resume else None,
    )


async def _attach_match_scores(db: AsyncSession, applications: list[Application]) -> None:
    """Rate a page of applications.

    Resolves the same resume per row that `/{id}/match` would -- the tailored
    resume when there is one, else the base -- but in two queries for the whole
    page rather than one lookup per row, so the list cannot disagree with the
    detail view.
    """
    if not applications:
        return

    base = await find_resume(db, None)
    tailored = await _tailored_resume_text(db, [a.id for a in applications])

    if base is None and not tailored:
        return

    base_text = base.extracted_text if base else None

    for application in applications:
        posting = application.posting
        if posting is None:
            continue
        resume_text = tailored.get(application.id) or base_text
        rated = rate_match(
            posting_raw_text=posting.raw_text,
            posting_extracted=posting.extracted,
            resume_text=resume_text,
        )
        # Set on the ORM object purely so the response model picks it up; these
        # are not mapped columns, so nothing is written back to the database.
        application.match_score = rated.score
        application.match_rating = rated.rating


async def _tailored_resume_text(
    db: AsyncSession, application_ids: list[uuid.UUID]
) -> dict[uuid.UUID, str]:
    """Newest tailored resume text per application, in one query."""
    if not application_ids:
        return {}

    result = await db.execute(
        select(Document.application_id, Document.extracted_text)
        .where(
            Document.kind == DocumentKind.tailored_resume,
            Document.application_id.in_(application_ids),
            Document.extracted_text.isnot(None),
        )
        .order_by(Document.application_id, Document.created_at.desc())
    )
    newest: dict[uuid.UUID, str] = {}
    for application_id, text in result.all():
        # Ordered newest-first per application, so the first win stands.
        newest.setdefault(application_id, text)
    return newest


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
