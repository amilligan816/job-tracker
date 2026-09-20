import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from app.models import (
    ApplicationStatus,
    AssistantRunKind,
    DocumentKind,
    EventKind,
    RemoteType,
)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------- companies


class CompanyBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    website: str | None = Field(default=None, max_length=512)
    industry: str | None = Field(default=None, max_length=255)
    notes: str | None = None


class CompanyCreate(CompanyBase):
    pass


class CompanyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    website: str | None = None
    industry: str | None = None
    notes: str | None = None


class CompanyRead(ORMModel, CompanyBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime


# ------------------------------------------------------------------------- job postings


class JobPostingBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    company_id: uuid.UUID | None = None
    location: str | None = Field(default=None, max_length=255)
    remote_type: RemoteType = RemoteType.unknown
    employment_type: str | None = Field(default=None, max_length=64)
    seniority: str | None = Field(default=None, max_length=64)
    salary_min: Decimal | None = None
    salary_max: Decimal | None = None
    salary_currency: str | None = Field(default=None, max_length=3)
    source_url: str | None = Field(default=None, max_length=1024)
    raw_text: str | None = None
    extracted: dict | None = None


class JobPostingCreate(JobPostingBase):
    pass


class JobPostingUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    company_id: uuid.UUID | None = None
    location: str | None = None
    remote_type: RemoteType | None = None
    employment_type: str | None = None
    seniority: str | None = None
    salary_min: Decimal | None = None
    salary_max: Decimal | None = None
    salary_currency: str | None = None
    source_url: str | None = None
    raw_text: str | None = None
    extracted: dict | None = None


class JobPostingRead(ORMModel, JobPostingBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    company: CompanyRead | None = None


# ---------------------------------------------------------------------- posting capture


class PostingCaptureRequest(BaseModel):
    """Capture a posting from a URL or a pasted blob, then structure it.

    Exactly one of `url` or `text` is required.
    """

    url: HttpUrl | None = None
    text: str | None = None
    # When false, the posting is stored verbatim with no LLM call.
    parse: bool = True


class ExtractedPosting(BaseModel):
    """Schema the model fills in. Every field is optional except the title."""

    title: str
    company_name: str | None = None
    location: str | None = None
    remote_type: RemoteType = RemoteType.unknown
    employment_type: str | None = None
    seniority: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    responsibilities: list[str] = Field(default_factory=list)
    requirements: list[str] = Field(default_factory=list)
    nice_to_have: list[str] = Field(default_factory=list)
    tech_stack: list[str] = Field(default_factory=list)
    benefits: list[str] = Field(default_factory=list)


# ------------------------------------------------------------------------ applications


class ApplicationBase(BaseModel):
    posting_id: uuid.UUID
    status: ApplicationStatus = ApplicationStatus.saved
    applied_on: date | None = None
    next_action: str | None = Field(default=None, max_length=512)
    next_action_on: date | None = None
    excitement: int | None = Field(default=None, ge=1, le=5)
    notes: str | None = None


class ApplicationCreate(ApplicationBase):
    pass


class ApplicationUpdate(BaseModel):
    status: ApplicationStatus | None = None
    applied_on: date | None = None
    next_action: str | None = None
    next_action_on: date | None = None
    excitement: int | None = Field(default=None, ge=1, le=5)
    notes: str | None = None


class ApplicationEventRead(ORMModel):
    id: uuid.UUID
    application_id: uuid.UUID
    kind: EventKind
    occurred_at: datetime
    summary: str
    detail: str | None = None


class ApplicationEventCreate(BaseModel):
    kind: EventKind = EventKind.note
    summary: str = Field(min_length=1, max_length=512)
    detail: str | None = None
    occurred_at: datetime | None = None


class ApplicationRead(ORMModel, ApplicationBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    posting: JobPostingRead | None = None
    # Filled in by the list endpoint when a resume is available; see /match for why.
    match_score: int | None = None
    match_rating: str | None = None


class ApplicationDetail(ApplicationRead):
    events: list[ApplicationEventRead] = Field(default_factory=list)
    documents: list["DocumentRead"] = Field(default_factory=list)


# --------------------------------------------------------------------------- documents


class DocumentRead(ORMModel):
    id: uuid.UUID
    application_id: uuid.UUID | None = None
    kind: DocumentKind
    filename: str
    content_type: str
    size_bytes: int
    storage_key: str
    created_at: datetime
    # True for the one base resume that tailored resumes are written from.
    is_base: bool = False
    # For a tailored resume: the base resume it came from.
    derived_from_id: uuid.UUID | None = None
    # Whether plain text could be read out of it; the matcher needs this.
    has_text: bool = False


class DocumentDownload(BaseModel):
    url: str
    expires_in: int


# ----------------------------------------------------------------------- match rating


class MatchSkill(ORMModel):
    skill: str
    weight: int
    source: str


class PostingMatch(BaseModel):
    """Deterministic resume-vs-posting rating. No model call involved."""

    # None when there is no resume, or the posting is too thin to rate.
    score: int | None
    rating: str
    confidence: str
    explanation: str
    matched: list[MatchSkill] = Field(default_factory=list)
    missing: list[MatchSkill] = Field(default_factory=list)
    extra: list[str] = Field(default_factory=list)
    coverage: float | None = None
    required_years: int | None = None
    resume_years: int | None = None
    years_basis: str | None = None
    resume_document_id: uuid.UUID | None = None


# --------------------------------------------------------------------------- assistant


class MatchAnalysisRequest(BaseModel):
    application_id: uuid.UUID
    resume_document_id: uuid.UUID | None = None


class MatchGap(BaseModel):
    requirement: str
    evidence: str | None = None
    severity: str


class MatchAnalysis(BaseModel):
    overall_fit: int = Field(ge=0, le=100)
    summary: str
    strengths: list[str] = Field(default_factory=list)
    gaps: list[MatchGap] = Field(default_factory=list)
    resume_suggestions: list[str] = Field(default_factory=list)
    talking_points: list[str] = Field(default_factory=list)


class CoverLetterRequest(BaseModel):
    application_id: uuid.UUID
    resume_document_id: uuid.UUID | None = None
    tone: str = Field(default="professional and direct", max_length=128)
    emphasis: str | None = Field(default=None, max_length=1024)


class InterviewPrepRequest(BaseModel):
    application_id: uuid.UUID
    resume_document_id: uuid.UUID | None = None
    round_type: str = Field(default="recruiter screen", max_length=128)


class AssistantRunRead(ORMModel):
    id: uuid.UUID
    application_id: uuid.UUID | None = None
    kind: AssistantRunKind
    model: str
    output_text: str | None = None
    output_json: dict | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    created_at: datetime


# ---------------------------------------------------------------------------- summary


class PipelineSummary(BaseModel):
    by_status: dict[str, int]
    total: int
    needs_action: int


ApplicationDetail.model_rebuild()
