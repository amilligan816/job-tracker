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
from sqlalchemy import select
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
    stmt = select(Document).order_by(Document.created_at.desc())
    if application_id:
        stmt = stmt.where(Document.application_id == application_id)
    if kind:
        stmt = stmt.where(Document.kind == kind)
    result = await db.execute(stmt.limit(limit).offset(offset))
    return result.scalars().all()


@router.post("", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    kind: DocumentKind = Form(default=DocumentKind.other),
    application_id: uuid.UUID | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
):
    if application_id:
        await get_or_404(db, Application, application_id)

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
    )
    db.add(document)
    try:
        await db.flush()
    except Exception:
        # Don't leave the object orphaned in the bucket if the row fails.
        await storage.delete_object(key)
        raise
    await db.refresh(document)
    return document


@router.get("/{document_id}", response_model=DocumentRead)
async def get_document(document_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    return await get_or_404(db, Document, document_id)


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
    await db.delete(document)
    await db.flush()
    await storage.delete_object(key)
