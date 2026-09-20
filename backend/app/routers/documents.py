import uuid

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import storage
from app.crud import get_or_404
from app.db import get_db
from app.models import Application, Document, DocumentKind
from app.schemas import DocumentDownload, DocumentRead
from app.textextract import extract_document_text

router = APIRouter(prefix="/documents", tags=["documents"])

MAX_UPLOAD_BYTES = 25 * 1024 * 1024


@router.get("", response_model=list[DocumentRead])
async def list_documents(
    db: AsyncSession = Depends(get_db),
    application_id: uuid.UUID | None = None,
    kind: DocumentKind | None = None,
    limit: int = Query(default=200, le=1000),
    offset: int = 0,
):
    stmt = select(Document).order_by(Document.is_base.desc(), Document.created_at.desc())
    if application_id:
        stmt = stmt.where(Document.application_id == application_id)
    if kind:
        stmt = stmt.where(Document.kind == kind)
    result = await db.execute(stmt.limit(limit).offset(offset))
    return [_with_text_flag(doc) for doc in result.scalars().all()]


@router.post("", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    kind: DocumentKind = Form(default=DocumentKind.other),
    application_id: uuid.UUID | None = Form(default=None),
    derived_from_id: uuid.UUID | None = Form(
        default=None, description="For a tailored resume: the base resume it was written from"
    ),
    make_base: bool = Form(
        default=False, description="Mark this base resume as the one to tailor from"
    ),
    db: AsyncSession = Depends(get_db),
):
    if application_id:
        await get_or_404(db, Application, application_id)

    if derived_from_id:
        if kind is not DocumentKind.tailored_resume:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Only a tailored resume can be derived from a base resume",
            )
        source = await get_or_404(db, Document, derived_from_id)
        if source.kind is not DocumentKind.base_resume:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{source.filename!r} is not a base resume",
            )

    if make_base and kind is not DocumentKind.base_resume:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Only a base resume can be set as the base",
        )

    data = await file.read()
    if not data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="The uploaded file is empty"
        )
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit",
        )

    filename = file.filename or "upload"
    content_type = file.content_type or "application/octet-stream"
    key = storage.build_key(kind.value, filename)

    await storage.put_object(key, data, content_type)

    # Text extraction is best-effort -- a .docx still stores and downloads fine,
    # it just won't be readable by the assistant.
    text = await extract_document_text(data, content_type, filename)

    document = Document(
        application_id=application_id,
        kind=kind,
        filename=filename,
        content_type=content_type,
        size_bytes=len(data),
        storage_key=key,
        extracted_text=text,
        derived_from_id=derived_from_id,
    )
    db.add(document)
    try:
        await db.flush()
    except Exception:
        # Don't leave the object orphaned in the bucket if the row fails.
        await storage.delete_object(key)
        raise
    await db.refresh(document)

    # The first base resume uploaded becomes the base automatically -- otherwise
    # the matcher has a resume it is pointedly not using.
    if kind is DocumentKind.base_resume and (make_base or not await _has_base(db)):
        await _promote_to_base(db, document)

    return _with_text_flag(document)


@router.post("/{document_id}/set-base", response_model=DocumentRead)
async def set_base_resume(document_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Make this the base resume that tailored resumes are written from."""
    document = await get_or_404(db, Document, document_id)
    if document.kind is not DocumentKind.base_resume:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Only a base resume can be set as the base",
        )
    await _promote_to_base(db, document)
    return _with_text_flag(document)


@router.get("/{document_id}", response_model=DocumentRead)
async def get_document(document_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    return _with_text_flag(await get_or_404(db, Document, document_id))


@router.get("/{document_id}/download", response_model=DocumentDownload)
async def download_document(document_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Hand back a short-lived presigned URL rather than proxying the bytes."""
    document = await get_or_404(db, Document, document_id)
    url, ttl = await storage.presigned_download_url(document.storage_key, document.filename)
    return DocumentDownload(url=url, expires_in=ttl)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    document = await get_or_404(db, Document, document_id)
    key = document.storage_key
    was_base = document.is_base

    await db.delete(document)
    await db.flush()
    await storage.delete_object(key)

    # Don't leave the user with base resumes but no designated base.
    if was_base:
        replacement = await _first_base_resume(db)
        if replacement is not None:
            await _promote_to_base(db, replacement)


# --------------------------------------------------------------------------- helpers


def _with_text_flag(document: Document) -> Document:
    """`has_text` is derived, not stored; the response model reads it off here."""
    document.has_text = document.extracted_text is not None
    return document


async def _has_base(db: AsyncSession) -> bool:
    result = await db.execute(select(Document.id).where(Document.is_base.is_(True)).limit(1))
    return result.scalar_one_or_none() is not None


async def _first_base_resume(db: AsyncSession) -> Document | None:
    result = await db.execute(
        select(Document)
        .where(Document.kind == DocumentKind.base_resume)
        .order_by(Document.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _promote_to_base(db: AsyncSession, document: Document) -> None:
    """Exactly one base at a time -- a partial unique index enforces it, so the
    old base must be cleared and flushed before the new one is set."""
    await db.execute(update(Document).where(Document.is_base.is_(True)).values(is_base=False))
    await db.flush()
    document.is_base = True
    await db.flush()
