import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.crud import get_or_404
from app.db import get_db
from app.llm import analyze_match, draft_cover_letter, draft_interview_prep
from app.models import (
    Application,
    AssistantRun,
    AssistantRunKind,
    Document,
    DocumentKind,
    JobPosting,
)
from app.schemas import (
    AssistantRunRead,
    CoverLetterRequest,
    InterviewPrepRequest,
    MatchAnalysisRequest,
)

router = APIRouter(prefix="/assistant", tags=["assistant"])


@router.get("/status")
async def assistant_status():
    settings = get_settings()
    return {"enabled": settings.assistant_enabled, "model": settings.anthropic_model}


@router.post("/match-analysis", response_model=AssistantRunRead)
async def match_analysis(payload: MatchAnalysisRequest, db: AsyncSession = Depends(get_db)):
    application, posting_text, resume_text, _company = await _context(
        db, payload.application_id, payload.resume_document_id
    )
    analysis, usage = await analyze_match(posting_text, resume_text)

    return await _record(
        db,
        application_id=application.id,
        kind=AssistantRunKind.match_analysis,
        output_json=analysis.model_dump(mode="json"),
        usage=usage,
        context={"resume_document_id": str(payload.resume_document_id or "")},
    )


@router.post("/cover-letter", response_model=AssistantRunRead)
async def cover_letter(payload: CoverLetterRequest, db: AsyncSession = Depends(get_db)):
    application, posting_text, resume_text, company = await _context(
        db, payload.application_id, payload.resume_document_id
    )
    text, usage = await draft_cover_letter(
        posting_text, resume_text, company, payload.tone, payload.emphasis
    )

    return await _record(
        db,
        application_id=application.id,
        kind=AssistantRunKind.cover_letter,
        output_text=text,
        usage=usage,
        context={"tone": payload.tone, "emphasis": payload.emphasis},
    )


@router.post("/interview-prep", response_model=AssistantRunRead)
async def interview_prep(payload: InterviewPrepRequest, db: AsyncSession = Depends(get_db)):
    application, posting_text, resume_text, company = await _context(
        db, payload.application_id, payload.resume_document_id
    )
    text, usage = await draft_interview_prep(posting_text, resume_text, company, payload.round_type)

    return await _record(
        db,
        application_id=application.id,
        kind=AssistantRunKind.interview_prep,
        output_text=text,
        usage=usage,
        context={"round_type": payload.round_type},
    )


@router.get("/runs", response_model=list[AssistantRunRead])
async def list_runs(
    db: AsyncSession = Depends(get_db),
    application_id: uuid.UUID | None = None,
    kind: AssistantRunKind | None = None,
    limit: int = Query(default=50, le=200),
):
    stmt = select(AssistantRun).order_by(AssistantRun.created_at.desc())
    if application_id:
        stmt = stmt.where(AssistantRun.application_id == application_id)
    if kind:
        stmt = stmt.where(AssistantRun.kind == kind)
    result = await db.execute(stmt.limit(limit))
    return result.scalars().all()


@router.get("/runs/{run_id}", response_model=AssistantRunRead)
async def get_run(run_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    return await get_or_404(db, AssistantRun, run_id)


# --------------------------------------------------------------------------- helpers


async def _context(
    db: AsyncSession, application_id: uuid.UUID, resume_document_id: uuid.UUID | None
) -> tuple[Application, str, str | None, str | None]:
    """Assemble posting text, resume text, and company name for one application."""
    result = await db.execute(
        select(Application)
        .options(selectinload(Application.posting).selectinload(JobPosting.company))
        .where(Application.id == application_id)
    )
    application = result.scalar_one_or_none()
    if application is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Application {application_id} not found"
        )

    posting = application.posting
    posting_text = posting.raw_text or _posting_digest(posting)
    if not posting_text.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="This posting has no description stored -- capture or paste one first",
        )

    resume = await _resolve_resume(db, application_id, resume_document_id)
    company = posting.company.name if posting.company else None
    return application, posting_text, resume, company


async def _resolve_resume(
    db: AsyncSession, application_id: uuid.UUID, resume_document_id: uuid.UUID | None
) -> str | None:
    if resume_document_id:
        document = await get_or_404(db, Document, resume_document_id)
        if not document.extracted_text:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"No readable text was extracted from {document.filename!r}. "
                    "Upload a PDF, .txt or .md version."
                ),
            )
        return document.extracted_text

    # Otherwise: the newest resume attached to this application, else the newest
    # unattached resume, so a single stored resume just works.
    result = await db.execute(
        select(Document)
        .where(
            Document.kind == DocumentKind.resume,
            Document.extracted_text.isnot(None),
            or_(
                Document.application_id == application_id,
                Document.application_id.is_(None),
            ),
        )
        .order_by(
            # Prefer one attached to this application.
            (Document.application_id == application_id).desc(),
            Document.created_at.desc(),
        )
        .limit(1)
    )
    document = result.scalar_one_or_none()
    return document.extracted_text if document else None


def _posting_digest(posting: JobPosting) -> str:
    """Fallback context when only structured fields were entered by hand."""
    parts = [f"Title: {posting.title}"]
    if posting.location:
        parts.append(f"Location: {posting.location}")
    if posting.seniority:
        parts.append(f"Seniority: {posting.seniority}")
    if posting.employment_type:
        parts.append(f"Employment type: {posting.employment_type}")
    for section in ("responsibilities", "requirements", "nice_to_have", "tech_stack"):
        values = (posting.extracted or {}).get(section) or []
        if values:
            parts.append(f"\n{section.replace('_', ' ').title()}:")
            parts.extend(f"- {v}" for v in values)
    return "\n".join(parts)


async def _record(
    db: AsyncSession,
    *,
    application_id: uuid.UUID,
    kind: AssistantRunKind,
    usage,
    output_text: str | None = None,
    output_json: dict | None = None,
    context: dict | None = None,
) -> AssistantRun:
    run = AssistantRun(
        application_id=application_id,
        kind=kind,
        model=get_settings().anthropic_model,
        prompt_context=context,
        output_text=output_text,
        output_json=output_json,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
    )
    db.add(run)
    await db.flush()
    await db.refresh(run)
    return run
