"""Picking which resume an application is judged against.

Shared by the deterministic matcher and the Claude assistant so both answer the
question the same way.

Precedence, most specific first:

1. A resume the caller named explicitly.
2. The tailored resume written for this application -- that is what would
   actually be sent, so it is what should be rated.
3. The designated base resume (`is_base`).
4. Failing that, the most recent base resume.
"""

import uuid

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document, DocumentKind


async def _first(db: AsyncSession, stmt: Select) -> Document | None:
    result = await db.execute(stmt.limit(1))
    return result.scalar_one_or_none()


async def find_resume(
    db: AsyncSession,
    application_id: uuid.UUID | None,
    document_id: uuid.UUID | None = None,
) -> Document | None:
    """The resume to judge against, or None if there isn't a usable one."""
    if document_id:
        return await db.get(Document, document_id)

    if application_id is not None:
        tailored = await _first(
            db,
            select(Document)
            .where(
                Document.kind == DocumentKind.tailored_resume,
                Document.application_id == application_id,
                Document.extracted_text.isnot(None),
            )
            .order_by(Document.created_at.desc()),
        )
        if tailored is not None:
            return tailored

    return await _first(
        db,
        select(Document)
        .where(
            Document.kind == DocumentKind.base_resume,
            Document.extracted_text.isnot(None),
        )
        # The designated base wins; otherwise the most recent one.
        .order_by(Document.is_base.desc(), Document.created_at.desc()),
    )


async def get_base_resume(db: AsyncSession) -> Document | None:
    """The document currently marked as the base resume, if any."""
    return await _first(
        db,
        select(Document).where(
            Document.is_base.is_(True), Document.kind == DocumentKind.base_resume
        ),
    )
