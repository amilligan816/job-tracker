import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class ApplicationStatus(enum.StrEnum):
    saved = "saved"
    applied = "applied"
    screening = "screening"
    interviewing = "interviewing"
    offer = "offer"
    accepted = "accepted"
    rejected = "rejected"
    withdrawn = "withdrawn"


class RemoteType(enum.StrEnum):
    onsite = "onsite"
    hybrid = "hybrid"
    remote = "remote"
    unknown = "unknown"


class DocumentKind(enum.StrEnum):
    """An artifact produced for, or attached to, one application.

    Resumes are no longer stored as a master document -- they are generated from
    the experience record and a template, so what lands here is the output.
    """

    resume = "resume"
    cover_letter = "cover_letter"
    interview_prep = "interview_prep"
    portfolio = "portfolio"
    offer_letter = "offer_letter"
    other = "other"


class ExperienceSource(enum.StrEnum):
    """Where an experience item came from, so the UI can show provenance."""

    imported = "imported"
    manual = "manual"
    chat = "chat"


class ChatRole(enum.StrEnum):
    user = "user"
    assistant = "assistant"


class EventKind(enum.StrEnum):
    status_change = "status_change"
    note = "note"
    interview = "interview"
    outreach = "outreach"
    followup = "followup"


class AssistantRunKind(enum.StrEnum):
    match_analysis = "match_analysis"
    cover_letter = "cover_letter"
    interview_prep = "interview_prep"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Company(TimestampMixin, Base):
    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    website: Mapped[str | None] = mapped_column(String(512))
    industry: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)

    postings: Mapped[list["JobPosting"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )


class JobPosting(TimestampMixin, Base):
    __tablename__ = "job_postings"

    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), index=True
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    location: Mapped[str | None] = mapped_column(String(255))
    remote_type: Mapped[RemoteType] = mapped_column(
        Enum(RemoteType, name="remote_type"), default=RemoteType.unknown, nullable=False
    )
    employment_type: Mapped[str | None] = mapped_column(String(64))
    seniority: Mapped[str | None] = mapped_column(String(64))

    salary_min: Mapped[float | None] = mapped_column(Numeric(12, 2))
    salary_max: Mapped[float | None] = mapped_column(Numeric(12, 2))
    salary_currency: Mapped[str | None] = mapped_column(String(3))

    source_url: Mapped[str | None] = mapped_column(String(1024))
    # Full posting text as captured, kept verbatim so re-parsing never needs a refetch.
    raw_text: Mapped[str | None] = mapped_column(Text)
    # Structured fields the extractor pulled out but that have no column of their own
    # (requirements, tech stack, benefits, ...).
    extracted: Mapped[dict | None] = mapped_column(JSONB)

    company: Mapped[Company | None] = relationship(back_populates="postings")
    applications: Mapped[list["Application"]] = relationship(
        back_populates="posting", cascade="all, delete-orphan"
    )


class Application(TimestampMixin, Base):
    __tablename__ = "applications"

    id: Mapped[uuid.UUID] = _uuid_pk()
    posting_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("job_postings.id", ondelete="CASCADE"), nullable=False, index=True
    )

    status: Mapped[ApplicationStatus] = mapped_column(
        Enum(ApplicationStatus, name="application_status"),
        default=ApplicationStatus.saved,
        nullable=False,
        index=True,
    )
    applied_on: Mapped[date | None] = mapped_column(Date)
    next_action: Mapped[str | None] = mapped_column(String(512))
    next_action_on: Mapped[date | None] = mapped_column(Date, index=True)
    # 1-5, how much the user wants this one. Drives sorting in the UI.
    excitement: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)

    posting: Mapped[JobPosting] = relationship(back_populates="applications")
    events: Mapped[list["ApplicationEvent"]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        order_by="ApplicationEvent.occurred_at.desc()",
    )
    documents: Mapped[list["Document"]] = relationship(back_populates="application")


class ApplicationEvent(Base):
    __tablename__ = "application_events"

    id: Mapped[uuid.UUID] = _uuid_pk()
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[EventKind] = mapped_column(Enum(EventKind, name="event_kind"), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    summary: Mapped[str] = mapped_column(String(512), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)

    application: Mapped[Application] = relationship(back_populates="events")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = _uuid_pk()
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("applications.id", ondelete="SET NULL"), index=True
    )
    kind: Mapped[DocumentKind] = mapped_column(
        Enum(DocumentKind, name="document_kind"), default=DocumentKind.other, nullable=False
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    # Object key in the MinIO bucket. Unique so an orphaned row can't shadow an object.
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    # Plain-text rendering, when we could produce one. The assistant reads this.
    extracted_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    application: Mapped[Application | None] = relationship(back_populates="documents")


class ExperienceProfile(TimestampMixin, Base):
    """The candidate's professional record.

    This replaces the stored base resume: a resume is rendered from here and a
    template, rather than a file everything else points at. Single-user app, so
    there is one row -- `get_or_create_profile` owns that.
    """

    __tablename__ = "experience_profiles"

    id: Mapped[uuid.UUID] = _uuid_pk()
    full_name: Mapped[str | None] = mapped_column(String(255))
    headline: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(64))
    location: Mapped[str | None] = mapped_column(String(255))
    # [{"label": "GitHub", "url": "..."}]
    links: Mapped[list | None] = mapped_column(JSONB)
    summary: Mapped[str | None] = mapped_column(Text)
    # Free-form skill list the candidate claims, beyond what the roles imply.
    skills: Mapped[list | None] = mapped_column(JSONB)

    roles: Mapped[list["ExperienceRole"]] = relationship(
        back_populates="profile",
        cascade="all, delete-orphan",
        order_by="ExperienceRole.sort_order",
    )
    stories: Mapped[list["ExperienceStory"]] = relationship(
        back_populates="profile",
        cascade="all, delete-orphan",
        order_by="ExperienceStory.created_at.desc()",
    )
    education: Mapped[list["Education"]] = relationship(
        back_populates="profile",
        cascade="all, delete-orphan",
        order_by="Education.sort_order",
    )


class ExperienceRole(Base):
    __tablename__ = "experience_roles"

    id: Mapped[uuid.UUID] = _uuid_pk()
    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("experience_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    location: Mapped[str | None] = mapped_column(String(255))
    employment_type: Mapped[str | None] = mapped_column(String(64))
    start_date: Mapped[date | None] = mapped_column(Date)
    # Null means current.
    end_date: Mapped[date | None] = mapped_column(Date)
    summary: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    source: Mapped[ExperienceSource] = mapped_column(
        Enum(ExperienceSource, name="experience_source"),
        default=ExperienceSource.manual,
        nullable=False,
    )

    profile: Mapped[ExperienceProfile] = relationship(back_populates="roles")
    highlights: Mapped[list["ExperienceHighlight"]] = relationship(
        back_populates="role",
        cascade="all, delete-orphan",
        order_by="ExperienceHighlight.sort_order",
    )
    stories: Mapped[list["ExperienceStory"]] = relationship(back_populates="role")


class ExperienceHighlight(Base):
    """One achievement bullet. These are what a generated resume draws from."""

    __tablename__ = "experience_highlights"

    id: Mapped[uuid.UUID] = _uuid_pk()
    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("experience_roles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    source: Mapped[ExperienceSource] = mapped_column(
        Enum(ExperienceSource, name="experience_source"),
        default=ExperienceSource.manual,
        nullable=False,
    )

    role: Mapped[ExperienceRole] = relationship(back_populates="highlights")


class ExperienceStory(Base):
    """A deeper narrative than a resume bullet can hold.

    This is what the chat is for: the detail behind an achievement that makes a
    cover letter specific and an interview answer real.
    """

    __tablename__ = "experience_stories"

    id: Mapped[uuid.UUID] = _uuid_pk()
    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("experience_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("experience_roles.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    skills: Mapped[list | None] = mapped_column(JSONB)
    source: Mapped[ExperienceSource] = mapped_column(
        Enum(ExperienceSource, name="experience_source"),
        default=ExperienceSource.chat,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    profile: Mapped[ExperienceProfile] = relationship(back_populates="stories")
    role: Mapped[ExperienceRole | None] = relationship(back_populates="stories")


class Education(Base):
    __tablename__ = "experience_education"

    id: Mapped[uuid.UUID] = _uuid_pk()
    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("experience_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    institution: Mapped[str] = mapped_column(String(255), nullable=False)
    credential: Mapped[str | None] = mapped_column(String(255))
    field: Mapped[str | None] = mapped_column(String(255))
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    profile: Mapped[ExperienceProfile] = relationship(back_populates="education")


class ExperienceMessage(Base):
    """One turn of the experience interview."""

    __tablename__ = "experience_messages"

    id: Mapped[uuid.UUID] = _uuid_pk()
    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("experience_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[ChatRole] = mapped_column(Enum(ChatRole, name="chat_role"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ResumeTemplate(TimestampMixin, Base):
    """How a generated resume is laid out."""

    __tablename__ = "resume_templates"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Ordered section keys, e.g. ["summary", "skills", "experience", "education"].
    sections: Mapped[list | None] = mapped_column(JSONB)
    # Rendering knobs: heading style, date format, bullets per role, page limit.
    options: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (
        Index(
            "uq_resume_templates_single_default",
            "is_default",
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )


class AssistantRun(Base):
    __tablename__ = "assistant_runs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[AssistantRunKind] = mapped_column(
        Enum(AssistantRunKind, name="assistant_run_kind"), nullable=False
    )
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_context: Mapped[dict | None] = mapped_column(JSONB)
    output_text: Mapped[str | None] = mapped_column(Text)
    output_json: Mapped[dict | None] = mapped_column(JSONB)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
