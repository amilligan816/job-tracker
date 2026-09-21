"""The candidate's professional record.

This is what used to be "the base resume". Keeping it as structured data rather
than a file means one source of truth that a resume can be rendered from, the
matcher can be scored against, and the assistant can be grounded in -- without
anything having to re-parse a document each time.
"""

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import ExperienceProfile, ExperienceRole

_PROFILE_LOADERS = (
    selectinload(ExperienceProfile.roles).selectinload(ExperienceRole.highlights),
    selectinload(ExperienceProfile.stories),
    selectinload(ExperienceProfile.education),
)


async def get_or_create_profile(db: AsyncSession) -> ExperienceProfile:
    """The single profile, created empty on first use.

    Single-user app: there is one record, and no screen should ever ask which.
    """
    result = await db.execute(
        select(ExperienceProfile).options(*_PROFILE_LOADERS).order_by(ExperienceProfile.created_at)
    )
    profile = result.scalars().first()
    if profile is not None:
        return profile

    profile = ExperienceProfile()
    db.add(profile)
    await db.flush()
    return await load_profile(db, profile.id)


async def load_profile(db: AsyncSession, profile_id: uuid.UUID) -> ExperienceProfile:
    """Reload the profile and its collections from the database.

    `populate_existing` is essential: without it SQLAlchemy hands back the
    identity-mapped profile with whatever relationships were already loaded, so
    rows added earlier in the same session are silently missing from the
    response.
    """
    result = await db.execute(
        select(ExperienceProfile)
        .options(*_PROFILE_LOADERS)
        .where(ExperienceProfile.id == profile_id)
        .execution_options(populate_existing=True)
    )
    return result.scalar_one()


def _format_period(start: date | None, end: date | None) -> str:
    if not start and not end:
        return ""
    fmt = "%b %Y"
    left = start.strftime(fmt) if start else "?"
    right = end.strftime(fmt) if end else "Present"
    return f"{left} – {right}"


def is_empty(profile: ExperienceProfile) -> bool:
    """Nothing worth scoring or writing from yet."""
    return not profile.roles and not profile.stories and not (profile.summary or "").strip()


def experience_text(profile: ExperienceProfile, *, include_stories: bool = True) -> str:
    """The whole record as plain text.

    One rendering serves two callers: the deterministic matcher scores against
    it, and the assistant is grounded in it. Using the same text for both means
    a match score and a cover letter can never disagree about what you have
    done.

    Stories are long; the matcher can skip them, since skills already surface in
    the role bullets and a story would just inflate the term count.
    """
    parts: list[str] = []

    if profile.full_name:
        parts.append(profile.full_name)
    if profile.headline:
        parts.append(profile.headline)
    contact = " · ".join(bit for bit in (profile.email, profile.phone, profile.location) if bit)
    if contact:
        parts.append(contact)
    for link in profile.links or []:
        if isinstance(link, dict) and link.get("url"):
            parts.append(f"{link.get('label') or 'Link'}: {link['url']}")

    if profile.summary:
        parts.extend(["", "SUMMARY", profile.summary])

    if profile.skills:
        parts.extend(["", "SKILLS", ", ".join(str(s) for s in profile.skills)])

    if profile.roles:
        parts.extend(["", "EXPERIENCE"])
        for role in profile.roles:
            period = _format_period(role.start_date, role.end_date)
            header = f"{role.title} — {role.company}"
            if role.location:
                header += f" ({role.location})"
            if period:
                header += f" | {period}"
            parts.append(header)
            if role.summary:
                parts.append(role.summary)
            parts.extend(f"- {h.text}" for h in role.highlights)
            parts.append("")

    if include_stories and profile.stories:
        parts.extend(["", "DETAILED EXPERIENCE"])
        for story in profile.stories:
            parts.append(f"{story.title}")
            if story.skills:
                parts.append("Skills: " + ", ".join(str(s) for s in story.skills))
            parts.append(story.body)
            parts.append("")

    if profile.education:
        parts.extend(["", "EDUCATION"])
        for item in profile.education:
            line = item.institution
            if item.credential:
                line = f"{item.credential}, {line}"
            period = _format_period(item.start_date, item.end_date)
            if period:
                line += f" | {period}"
            parts.append(line)
            if item.notes:
                parts.append(item.notes)

    return "\n".join(parts).strip()


async def profile_text(db: AsyncSession, *, include_stories: bool = True) -> str | None:
    """Convenience for callers that just need the text, or None if empty."""
    profile = await get_or_create_profile(db)
    if is_empty(profile):
        return None
    return experience_text(profile, include_stories=include_stories)
