"""Small shared helpers over the session. Routers hold the HTTP semantics."""

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Base


async def get_or_404[ModelT: Base](
    db: AsyncSession, model: type[ModelT], obj_id: uuid.UUID
) -> ModelT:
    obj = await db.get(model, obj_id)
    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{model.__name__} {obj_id} not found",
        )
    return obj


async def get_by_field[ModelT: Base](
    db: AsyncSession, model: type[ModelT], field: str, value
) -> ModelT | None:
    result = await db.execute(select(model).where(getattr(model, field) == value))
    return result.scalar_one_or_none()


def apply_updates(obj, payload) -> None:
    """Assign only the fields the client actually sent."""
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(obj, field, value)
