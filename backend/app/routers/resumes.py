import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import storage
from app.crud import get_or_404
from app.db import get_db
from app.experience import experience_text, format_period, get_or_create_profile, is_empty
from app.llm import tailor_resume
from app.models import Application, Document, DocumentKind, JobPosting, ResumeTemplate
from app.render import (
    DOCX_MEDIA_TYPE,
    PDF_MEDIA_TYPE,
    default_filename,
    resume_blocks,
    to_docx,
    to_pdf,
)
from app.schemas import (
    ExportFormat,
    ResumeBuildRequest,
    ResumeBuildResult,
    ResumeTemplateCreate,
    ResumeTemplateRead,
)

router = APIRouter(prefix="/resumes", tags=["resumes"])

DEFAULT_SECTIONS = ["summary", "skills", "experience", "education"]
DEFAULT_MAX_HIGHLIGHTS = 4


@router.get("/templates", response_model=list[ResumeTemplateRead])
async def list_templates(db: AsyncSession = Depends(get_db)):
    await _ensure_default_template(db)
    result = await db.execute(
        select(ResumeTemplate).order_by(ResumeTemplate.is_default.desc(), ResumeTemplate.name)
    )
    return result.scalars().all()


@router.post("/templates", response_model=ResumeTemplateRead, status_code=status.HTTP_201_CREATED)
async def create_template(payload: ResumeTemplateCreate, db: AsyncSession = Depends(get_db)):
    unknown = set(payload.sections) - set(DEFAULT_SECTIONS)
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown section(s): {', '.join(sorted(unknown))}",
        )
    template = ResumeTemplate(
        name=payload.name,
        sections=payload.sections,
        options=payload.options,
        is_default=False,
    )
    db.add(template)
    await db.flush()
    await db.refresh(template)
    return template


@router.post("/build", response_model=ResumeBuildResult)
async def build_resume(payload: ResumeBuildRequest, db: AsyncSession = Depends(get_db)):
    """Render a resume for one application from the experience record.

    With `tailor` off this is a plain render of the record and costs nothing.
    With it on, Claude chooses and sharpens the highlights -- but the companies,
    titles and dates always come from the record, so they cannot be invented.
    """
    profile = await get_or_create_profile(db)
    if is_empty(profile):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Your experience record is empty — import a resume or add a role first.",
        )

    application = await _load_application(db, payload.application_id)
    template = await _resolve_template(db, payload.template_id)
    sections = template.sections or DEFAULT_SECTIONS
    max_highlights = (template.options or {}).get("max_highlights_per_role", DEFAULT_MAX_HIGHLIGHTS)

    summary = profile.summary
    skills = list(profile.skills or [])
    roles_by_id = {role.id: role for role in profile.roles}
    chosen: list[dict] = []

    if payload.tailor:
        posting = application.posting
        posting_text = (posting.raw_text if posting else None) or (posting.title if posting else "")
        catalogue = "\n".join(
            f"- {role.id}: {role.title} at {role.company}" for role in profile.roles
        )
        tailored, _usage = await tailor_resume(
            experience_text(profile), posting_text, catalogue, max_highlights
        )

        summary = tailored.summary or summary
        skills = tailored.skills or skills
        for entry in tailored.roles:
            role = roles_by_id.get(entry.role_id)
            # A role_id the model invented is dropped rather than rendered.
            if role is None or not entry.include:
                continue
            chosen.append(_role_dict(role, entry.highlights[:max_highlights]))

    if not chosen:
        # Untailored, or tailoring returned nothing usable: render the record.
        chosen = [
            _role_dict(role, [h.text for h in role.highlights][:max_highlights])
            for role in profile.roles
        ]

    blocks = resume_blocks(
        summary=summary,
        skills=skills,
        roles=chosen,
        education=[
            {
                "institution": item.institution,
                "credential": item.credential,
                "period": format_period(item.start_date, item.end_date),
            }
            for item in profile.education
        ],
        sections=sections,
    )

    title = profile.full_name or "Resume"
    contact = " · ".join(
        bit for bit in (profile.headline, profile.email, profile.phone, profile.location) if bit
    )
    preview = _preview(title, contact, blocks)

    if payload.export_format is None:
        return ResumeBuildResult(document=None, preview=preview, tailored=payload.tailor)

    role_label = _role_label(application)
    if payload.export_format is ExportFormat.docx:
        data = await run_in_threadpool(to_docx, title, blocks, contact or None)
        media_type = DOCX_MEDIA_TYPE
    else:
        data = await run_in_threadpool(to_pdf, title, blocks, contact or None)
        media_type = PDF_MEDIA_TYPE

    filename = default_filename("Resume", payload.export_format.value, role_label)
    key = storage.build_key(DocumentKind.resume.value, filename)
    await storage.put_object(key, data, media_type)

    document = Document(
        application_id=application.id,
        kind=DocumentKind.resume,
        filename=filename,
        content_type=media_type,
        size_bytes=len(data),
        storage_key=key,
        extracted_text=preview,
    )
    db.add(document)
    try:
        await db.flush()
    except Exception:
        await storage.delete_object(key)
        raise
    await db.refresh(document)
    document.has_text = True

    return ResumeBuildResult(document=document, preview=preview, tailored=payload.tailor)


# --------------------------------------------------------------------------- helpers


def _role_dict(role, highlights: list[str]) -> dict:
    return {
        "title": role.title,
        "company": role.company,
        "location": role.location,
        "period": format_period(role.start_date, role.end_date),
        "summary": role.summary,
        "highlights": highlights,
    }


def _role_label(application: Application) -> str | None:
    posting = application.posting
    if posting is None:
        return None
    company = posting.company.name if posting.company else None
    return f"{posting.title} at {company}" if company else posting.title


def _preview(title: str, contact: str, blocks) -> str:
    lines = [title]
    if contact:
        lines.append(contact)
    lines.append("")
    for block in blocks:
        if block.kind == "heading":
            lines.extend(["", block.text.upper() if block.level <= 2 else block.text])
        elif block.kind == "bullet":
            lines.append(f"- {block.text}")
        else:
            lines.append(block.text)
    return "\n".join(lines).strip()


async def _load_application(db: AsyncSession, application_id: uuid.UUID) -> Application:
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
    return application


async def _ensure_default_template(db: AsyncSession) -> ResumeTemplate:
    result = await db.execute(select(ResumeTemplate).where(ResumeTemplate.is_default.is_(True)))
    template = result.scalar_one_or_none()
    if template is not None:
        return template

    template = ResumeTemplate(
        name="Standard",
        is_default=True,
        sections=DEFAULT_SECTIONS,
        options={"max_highlights_per_role": DEFAULT_MAX_HIGHLIGHTS},
    )
    db.add(template)
    await db.flush()
    return template


async def _resolve_template(db: AsyncSession, template_id: uuid.UUID | None) -> ResumeTemplate:
    if template_id:
        return await get_or_404(db, ResumeTemplate, template_id)
    return await _ensure_default_template(db)
