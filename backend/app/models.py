import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
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
    resume = "resume"
    cover_letter = "cover_letter"
    portfolio = "portfolio"
    offer_letter = "offer_letter"
    other = "other"


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
