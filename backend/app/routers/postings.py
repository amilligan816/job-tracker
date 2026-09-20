import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.crud import apply_updates, get_by_field, get_or_404
from app.db import get_db
from app.llm import extract_posting
from app.models import Company, JobPosting
from app.schemas import (
    JobPostingCreate,
    JobPostingRead,
    JobPostingUpdate,
    PostingCaptureRequest,
)
from app.textextract import fetch_posting_text

router = APIRouter(prefix="/postings", tags=["postings"])

_WITH_COMPANY = selectinload(JobPosting.company)


@router.get("", response_model=list[JobPostingRead])
async def list_postings(
    db: AsyncSession = Depends(get_db),
    company_id: uuid.UUID | None = None,
    q: str | None = Query(default=None, description="Case-insensitive title filter"),
    limit: int = Query(default=100, le=500),
    offset: int = 0,
):
    stmt = select(JobPosting).options(_WITH_COMPANY).order_by(JobPosting.created_at.desc())
    if company_id:
        stmt = stmt.where(JobPosting.company_id == company_id)
    if q:
        stmt = stmt.where(JobPosting.title.ilike(f"%{q}%"))
    result = await db.execute(stmt.limit(limit).offset(offset))
    return result.scalars().all()


@router.post("", response_model=JobPostingRead, status_code=status.HTTP_201_CREATED)
async def create_posting(payload: JobPostingCreate, db: AsyncSession = Depends(get_db)):
    if payload.company_id:
        await get_or_404(db, Company, payload.company_id)
    posting = JobPosting(**payload.model_dump())
    db.add(posting)
    await db.flush()
    return await _reload(db, posting.id)


@router.post("/capture", response_model=JobPostingRead, status_code=status.HTTP_201_CREATED)
async def capture_posting(payload: PostingCaptureRequest, db: AsyncSession = Depends(get_db)):
    """Capture a posting from a URL or pasted text, optionally structuring it.

    The raw text is always stored, so a failed or skipped parse still leaves a
    usable record that can be re-parsed later.
    """
    if bool(payload.url) == bool(payload.text):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide exactly one of `url` or `text`",
        )

    if payload.url:
        try:
            raw_text = await fetch_posting_text(str(payload.url))
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Could not fetch the posting: {exc}",
            ) from exc
        if len(raw_text) < 200:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "That page returned almost no text -- it probably renders the "
                    "posting in the browser. Paste the description instead."
                ),
            )
    else:
        raw_text = payload.text or ""

    posting = JobPosting(
        title="Untitled posting",
        source_url=str(payload.url) if payload.url else None,
        raw_text=raw_text,
    )

    if payload.parse:
        extracted, _usage = await extract_posting(raw_text)
        _apply_extraction(posting, extracted)
        posting.company_id = await _resolve_company(db, extracted.company_name)

    db.add(posting)
    await db.flush()
    return await _reload(db, posting.id)


@router.post("/{posting_id}/reparse", response_model=JobPostingRead)
async def reparse_posting(posting_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Re-run extraction over the stored raw text."""
    posting = await get_or_404(db, JobPosting, posting_id)
    if not posting.raw_text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="This posting has no stored raw text to re-parse",
        )
    extracted, _usage = await extract_posting(posting.raw_text)
    _apply_extraction(posting, extracted)
    if posting.company_id is None:
        posting.company_id = await _resolve_company(db, extracted.company_name)
    await db.flush()
    return await _reload(db, posting.id)


@router.get("/{posting_id}", response_model=JobPostingRead)
async def get_posting(posting_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    posting = await _reload(db, posting_id)
    if posting is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Posting not found")
    return posting


@router.patch("/{posting_id}", response_model=JobPostingRead)
async def update_posting(
    posting_id: uuid.UUID, payload: JobPostingUpdate, db: AsyncSession = Depends(get_db)
):
    posting = await get_or_404(db, JobPosting, posting_id)
    if payload.company_id:
        await get_or_404(db, Company, payload.company_id)
    apply_updates(posting, payload)
    await db.flush()
    return await _reload(db, posting.id)


@router.delete("/{posting_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_posting(posting_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    posting = await get_or_404(db, JobPosting, posting_id)
    await db.delete(posting)


# --------------------------------------------------------------------------- helpers


async def _reload(db: AsyncSession, posting_id: uuid.UUID) -> JobPosting | None:
    """Re-select with the company eagerly loaded, so response_model can serialise it."""
    result = await db.execute(
        select(JobPosting).options(_WITH_COMPANY).where(JobPosting.id == posting_id)
    )
    return result.scalar_one_or_none()


def _apply_extraction(posting: JobPosting, extracted) -> None:
    posting.title = extracted.title
    posting.location = extracted.location
    posting.remote_type = extracted.remote_type
    posting.employment_type = extracted.employment_type
    posting.seniority = extracted.seniority
    posting.salary_min = extracted.salary_min
    posting.salary_max = extracted.salary_max
    posting.salary_currency = extracted.salary_currency
    posting.extracted = extracted.model_dump(mode="json")


async def _resolve_company(db: AsyncSession, name: str | None) -> uuid.UUID | None:
    """Reuse an existing company row by name, or create one."""
    if not name or not name.strip():
        return None
    name = name.strip()
    existing = await get_by_field(db, Company, "name", name)
    if existing:
        return existing.id
    company = Company(name=name)
    db.add(company)
    await db.flush()
    return company.id
