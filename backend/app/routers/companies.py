import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import apply_updates, get_by_field, get_or_404
from app.db import get_db
from app.models import Company
from app.schemas import CompanyCreate, CompanyRead, CompanyUpdate

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("", response_model=list[CompanyRead])
async def list_companies(
    db: AsyncSession = Depends(get_db),
    q: str | None = Query(default=None, description="Case-insensitive name filter"),
    limit: int = Query(default=100, le=500),
    offset: int = 0,
):
    stmt = select(Company).order_by(Company.name)
    if q:
        stmt = stmt.where(Company.name.ilike(f"%{q}%"))
    result = await db.execute(stmt.limit(limit).offset(offset))
    return result.scalars().all()


@router.post("", response_model=CompanyRead, status_code=status.HTTP_201_CREATED)
async def create_company(payload: CompanyCreate, db: AsyncSession = Depends(get_db)):
    if await get_by_field(db, Company, "name", payload.name):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A company named {payload.name!r} already exists",
        )
    company = Company(**payload.model_dump())
    db.add(company)
    await db.flush()
    await db.refresh(company)
    return company


@router.get("/{company_id}", response_model=CompanyRead)
async def get_company(company_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    return await get_or_404(db, Company, company_id)


@router.patch("/{company_id}", response_model=CompanyRead)
async def update_company(
    company_id: uuid.UUID, payload: CompanyUpdate, db: AsyncSession = Depends(get_db)
):
    company = await get_or_404(db, Company, company_id)
    apply_updates(company, payload)
    await db.flush()
    await db.refresh(company)
    return company


@router.delete("/{company_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_company(company_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    company = await get_or_404(db, Company, company_id)
    await db.delete(company)
