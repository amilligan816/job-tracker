import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.crud import apply_updates, get_or_404
from app.db import get_db
from app.experience import experience_text, get_or_create_profile, is_empty, load_profile
from app.llm import extract_experience, interview_turn
from app.models import (
    ChatRole,
    Education,
    ExperienceHighlight,
    ExperienceMessage,
    ExperienceProfile,
    ExperienceRole,
    ExperienceSource,
    ExperienceStory,
)
from app.schemas import (
    ChatMessageRead,
    ChatTurnRequest,
    ChatTurnResponse,
    EducationCreate,
    EducationRead,
    EducationUpdate,
    HighlightCreate,
    HighlightRead,
    HighlightUpdate,
    ImportedExperience,
    ProfileRead,
    ProfileUpdate,
    RoleCreate,
    RoleRead,
    RoleUpdate,
    StoryCreate,
    StoryRead,
    StoryUpdate,
)
from app.textextract import extract_document_text

router = APIRouter(prefix="/experience", tags=["experience"])

MAX_IMPORT_BYTES = 25 * 1024 * 1024
# Plenty for an interview, and keeps a long-running conversation from growing
# the request without bound.
MAX_CHAT_HISTORY = 40


@router.get("", response_model=ProfileRead)
async def get_profile(db: AsyncSession = Depends(get_db)):
    """The whole record. Created empty on first call, so the UI never 404s."""
    profile = await get_or_create_profile(db)
    return _as_read(profile)


@router.patch("", response_model=ProfileRead)
async def update_profile(payload: ProfileUpdate, db: AsyncSession = Depends(get_db)):
    profile = await get_or_create_profile(db)
    updates = payload.model_dump(exclude_unset=True)
    if "links" in updates and updates["links"] is not None:
        updates["links"] = [link for link in updates["links"]]
    for field, value in updates.items():
        setattr(profile, field, value)
    await db.flush()
    return _as_read(await load_profile(db, profile.id))


@router.get("/text", response_model=dict)
async def get_profile_text(db: AsyncSession = Depends(get_db)):
    """The plain-text rendering the matcher scores and the assistant reads.

    Exposed so you can see exactly what the model is being told about you.
    """
    profile = await get_or_create_profile(db)
    return {"text": experience_text(profile), "is_empty": is_empty(profile)}


# ---------------------------------------------------------------------------- import


@router.post("/import", response_model=ImportedExperience)
async def import_from_resume(file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    """Read a resume and return structured career data for review.

    Nothing is saved here and the file is not stored -- the record is the
    artifact now, not the document it came from. The user confirms what lands
    in it via /import/apply.
    """
    data = await file.read()
    if not data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="The uploaded file is empty"
        )
    if len(data) > MAX_IMPORT_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds the {MAX_IMPORT_BYTES // (1024 * 1024)} MB limit",
        )

    text = await extract_document_text(
        data, file.content_type or "application/octet-stream", file.filename or "resume"
    )
    if not text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "No readable text could be extracted. PDF, Word (.docx), text and "
                "markdown work; a scanned image or legacy .doc does not."
            ),
        )

    imported, _usage = await extract_experience(text)
    return imported


@router.post("/import/apply", response_model=ProfileRead)
async def apply_import(payload: ImportedExperience, db: AsyncSession = Depends(get_db)):
    """Merge reviewed import results into the record.

    Roles are appended rather than replacing what is there, so importing a
    second resume adds history instead of destroying it. Profile fields only
    fill blanks.
    """
    profile = await get_or_create_profile(db)

    for field in ("full_name", "headline", "email", "phone", "location", "summary"):
        value = getattr(payload, field)
        if value and not getattr(profile, field):
            setattr(profile, field, value)

    if payload.skills:
        existing = {s.lower() for s in (profile.skills or [])}
        profile.skills = list(profile.skills or []) + [
            s for s in payload.skills if s.lower() not in existing
        ]

    # Re-importing the same resume is a likely mistake; skip anything already
    # recorded rather than quietly doubling the user's history.
    existing_roles = {
        (r.company.strip().lower(), r.title.strip().lower(), r.start_date) for r in profile.roles
    }
    existing_education = {
        (e.institution.strip().lower(), (e.credential or "").strip().lower())
        for e in profile.education
    }

    next_order = len(profile.roles)
    for index, role_in in enumerate(payload.roles):
        key = (role_in.company.strip().lower(), role_in.title.strip().lower(), role_in.start_date)
        if key in existing_roles:
            continue
        existing_roles.add(key)

        role = ExperienceRole(
            profile_id=profile.id,
            source=ExperienceSource.imported,
            **role_in.model_dump(exclude={"highlights", "sort_order"}),
            sort_order=next_order + index,
        )
        db.add(role)
        await db.flush()
        for position, highlight in enumerate(role_in.highlights):
            db.add(
                ExperienceHighlight(
                    role_id=role.id,
                    text=highlight.text,
                    sort_order=position,
                    source=ExperienceSource.imported,
                )
            )

    education_order = len(profile.education)
    for index, education_in in enumerate(payload.education):
        key = (
            education_in.institution.strip().lower(),
            (education_in.credential or "").strip().lower(),
        )
        if key in existing_education:
            continue
        existing_education.add(key)

        db.add(
            Education(
                profile_id=profile.id,
                **education_in.model_dump(exclude={"sort_order"}),
                sort_order=education_order + index,
            )
        )

    await db.flush()
    return _as_read(await load_profile(db, profile.id))


# ------------------------------------------------------------------------------ chat


@router.get("/chat", response_model=list[ChatMessageRead])
async def get_chat(db: AsyncSession = Depends(get_db)):
    profile = await get_or_create_profile(db)
    result = await db.execute(
        select(ExperienceMessage)
        .where(ExperienceMessage.profile_id == profile.id)
        .order_by(ExperienceMessage.created_at)
    )
    return result.scalars().all()


@router.post("/chat", response_model=ChatTurnResponse)
async def send_chat(payload: ChatTurnRequest, db: AsyncSession = Depends(get_db)):
    """One interview turn. Stories it proposes are returned, not saved."""
    profile = await get_or_create_profile(db)

    result = await db.execute(
        select(ExperienceMessage)
        .where(ExperienceMessage.profile_id == profile.id)
        .order_by(ExperienceMessage.created_at)
        .limit(MAX_CHAT_HISTORY)
    )
    history = [{"role": m.role.value, "content": m.content} for m in result.scalars().all()]

    db.add(ExperienceMessage(profile_id=profile.id, role=ChatRole.user, content=payload.message))

    turn, _usage = await interview_turn(experience_text(profile), history, payload.message)

    reply = ExperienceMessage(profile_id=profile.id, role=ChatRole.assistant, content=turn.reply)
    db.add(reply)
    await db.flush()
    await db.refresh(reply)

    return ChatTurnResponse(reply=reply, proposed_stories=turn.proposed_stories)


@router.delete("/chat", status_code=status.HTTP_204_NO_CONTENT)
async def clear_chat(db: AsyncSession = Depends(get_db)):
    """Start the interview over. Saved stories are untouched."""
    profile = await get_or_create_profile(db)
    await db.execute(delete(ExperienceMessage).where(ExperienceMessage.profile_id == profile.id))


# ----------------------------------------------------------------------------- roles


@router.post("/roles", response_model=RoleRead, status_code=status.HTTP_201_CREATED)
async def create_role(payload: RoleCreate, db: AsyncSession = Depends(get_db)):
    profile = await get_or_create_profile(db)
    data = payload.model_dump(exclude={"highlights"})
    role = ExperienceRole(profile_id=profile.id, source=ExperienceSource.manual, **data)
    db.add(role)
    await db.flush()

    for index, highlight in enumerate(payload.highlights):
        db.add(
            ExperienceHighlight(
                role_id=role.id,
                text=highlight.text,
                sort_order=highlight.sort_order or index,
                source=ExperienceSource.manual,
            )
        )
    await db.flush()
    return await _reload_role(db, role.id)


@router.patch("/roles/{role_id}", response_model=RoleRead)
async def update_role(role_id: uuid.UUID, payload: RoleUpdate, db: AsyncSession = Depends(get_db)):
    role = await get_or_404(db, ExperienceRole, role_id)
    apply_updates(role, payload)
    await db.flush()
    return await _reload_role(db, role_id)


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(role_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    await db.delete(await get_or_404(db, ExperienceRole, role_id))


@router.post(
    "/roles/{role_id}/highlights",
    response_model=HighlightRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_highlight(
    role_id: uuid.UUID, payload: HighlightCreate, db: AsyncSession = Depends(get_db)
):
    await get_or_404(db, ExperienceRole, role_id)
    highlight = ExperienceHighlight(
        role_id=role_id,
        text=payload.text,
        sort_order=payload.sort_order,
        source=ExperienceSource.manual,
    )
    db.add(highlight)
    await db.flush()
    await db.refresh(highlight)
    return highlight


@router.patch("/highlights/{highlight_id}", response_model=HighlightRead)
async def update_highlight(
    highlight_id: uuid.UUID, payload: HighlightUpdate, db: AsyncSession = Depends(get_db)
):
    highlight = await get_or_404(db, ExperienceHighlight, highlight_id)
    apply_updates(highlight, payload)
    await db.flush()
    await db.refresh(highlight)
    return highlight


@router.delete("/highlights/{highlight_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_highlight(highlight_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    await db.delete(await get_or_404(db, ExperienceHighlight, highlight_id))


# --------------------------------------------------------------------------- stories


@router.post("/stories", response_model=StoryRead, status_code=status.HTTP_201_CREATED)
async def create_story(payload: StoryCreate, db: AsyncSession = Depends(get_db)):
    profile = await get_or_create_profile(db)
    if payload.role_id:
        role = await get_or_404(db, ExperienceRole, payload.role_id)
        if role.profile_id != profile.id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="That role belongs to a different profile",
            )

    story = ExperienceStory(profile_id=profile.id, **payload.model_dump())
    db.add(story)
    await db.flush()
    await db.refresh(story)
    return story


@router.patch("/stories/{story_id}", response_model=StoryRead)
async def update_story(
    story_id: uuid.UUID, payload: StoryUpdate, db: AsyncSession = Depends(get_db)
):
    story = await get_or_404(db, ExperienceStory, story_id)
    apply_updates(story, payload)
    await db.flush()
    await db.refresh(story)
    return story


@router.delete("/stories/{story_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_story(story_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    await db.delete(await get_or_404(db, ExperienceStory, story_id))


# ------------------------------------------------------------------------- education


@router.post("/education", response_model=EducationRead, status_code=status.HTTP_201_CREATED)
async def create_education(payload: EducationCreate, db: AsyncSession = Depends(get_db)):
    profile = await get_or_create_profile(db)
    item = Education(profile_id=profile.id, **payload.model_dump())
    db.add(item)
    await db.flush()
    await db.refresh(item)
    return item


@router.patch("/education/{education_id}", response_model=EducationRead)
async def update_education(
    education_id: uuid.UUID, payload: EducationUpdate, db: AsyncSession = Depends(get_db)
):
    item = await get_or_404(db, Education, education_id)
    apply_updates(item, payload)
    await db.flush()
    await db.refresh(item)
    return item


@router.delete("/education/{education_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_education(education_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    await db.delete(await get_or_404(db, Education, education_id))


# --------------------------------------------------------------------------- helpers


def _as_read(profile: ExperienceProfile) -> ProfileRead:
    read = ProfileRead.model_validate(profile)
    read.is_empty = is_empty(profile)
    return read


async def _reload_role(db: AsyncSession, role_id: uuid.UUID) -> ExperienceRole:
    """Re-select with highlights loaded so the response model can serialise them."""
    result = await db.execute(
        select(ExperienceRole)
        .options(selectinload(ExperienceRole.highlights))
        .where(ExperienceRole.id == role_id)
    )
    return result.scalar_one()
