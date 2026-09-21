import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from app.models import (
    ApplicationStatus,
    AssistantRunKind,
    ChatRole,
    DocumentKind,
    EventKind,
    ExperienceSource,
    MailAccountStatus,
    MailProviderKind,
    RemoteType,
    SuggestionSource,
    SuggestionState,
)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def _empty_when_null(value):
    """Read a nullable JSONB column as the empty collection it means.

    `Field(default_factory=list)` only covers a *missing* key. These arrive from
    the ORM as a present `None` -- a row that has never had links or skills set
    -- which is a validation error rather than a default. The API contract is a
    list, so the null becomes one here instead of 500ing on a fresh profile.
    """
    if value is None:
        return []
    return value


def _empty_dict_when_null(value):
    return {} if value is None else value


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
    """Schema the model fills in. Every field is optional except the title.

    `is_job_posting` exists so the model has somewhere to put "this text is not
    a posting". Without it, a required `title` forces a made-up answer out of
    whatever it was given -- a careers-page shell becomes a posting titled after
    the page's breadcrumbs.
    """

    is_job_posting: bool = True
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
    # Whether plain text could be read out of it.
    has_text: bool = False


class DocumentDownload(BaseModel):
    url: str
    expires_in: int


# --------------------------------------------------------------------------- experience


class HighlightBase(BaseModel):
    text: str = Field(min_length=1)
    sort_order: int = 0


class HighlightCreate(HighlightBase):
    pass


class HighlightUpdate(BaseModel):
    text: str | None = Field(default=None, min_length=1)
    sort_order: int | None = None


class HighlightRead(ORMModel, HighlightBase):
    id: uuid.UUID
    source: ExperienceSource


class RoleBase(BaseModel):
    company: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=255)
    location: str | None = None
    employment_type: str | None = None
    start_date: date | None = None
    # Null means current.
    end_date: date | None = None
    summary: str | None = None
    sort_order: int = 0


class RoleCreate(RoleBase):
    highlights: list[HighlightCreate] = Field(default_factory=list)


class RoleUpdate(BaseModel):
    company: str | None = Field(default=None, min_length=1)
    title: str | None = Field(default=None, min_length=1)
    location: str | None = None
    employment_type: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    summary: str | None = None
    sort_order: int | None = None


class RoleRead(ORMModel, RoleBase):
    id: uuid.UUID
    source: ExperienceSource
    highlights: list[HighlightRead] = Field(default_factory=list)


class StoryBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    body: str = Field(min_length=1)
    role_id: uuid.UUID | None = None
    skills: list[str] = Field(default_factory=list)

    _skills_null = field_validator("skills", mode="before")(_empty_when_null)


class StoryCreate(StoryBase):
    source: ExperienceSource = ExperienceSource.manual


class StoryUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1)
    body: str | None = Field(default=None, min_length=1)
    role_id: uuid.UUID | None = None
    skills: list[str] | None = None


class StoryRead(ORMModel, StoryBase):
    id: uuid.UUID
    source: ExperienceSource
    created_at: datetime


class EducationBase(BaseModel):
    institution: str = Field(min_length=1, max_length=255)
    credential: str | None = None
    field: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    notes: str | None = None
    sort_order: int = 0


class EducationCreate(EducationBase):
    pass


class EducationUpdate(BaseModel):
    institution: str | None = Field(default=None, min_length=1)
    credential: str | None = None
    field: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    notes: str | None = None
    sort_order: int | None = None


class EducationRead(ORMModel, EducationBase):
    id: uuid.UUID


class ProfileLink(BaseModel):
    label: str
    url: str


class ProfileUpdate(BaseModel):
    full_name: str | None = None
    headline: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    links: list[ProfileLink] | None = None
    summary: str | None = None
    skills: list[str] | None = None


class ProfileRead(ORMModel):
    id: uuid.UUID
    full_name: str | None = None
    headline: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    links: list[ProfileLink] = Field(default_factory=list)
    summary: str | None = None
    skills: list[str] = Field(default_factory=list)
    roles: list[RoleRead] = Field(default_factory=list)
    stories: list[StoryRead] = Field(default_factory=list)
    education: list[EducationRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    # True when there is nothing to score or write from yet.
    is_empty: bool = False

    _links_null = field_validator("links", "skills", mode="before")(_empty_when_null)


class ImportedExperience(BaseModel):
    """What the model pulls out of an uploaded resume, for the user to review."""

    full_name: str | None = None
    headline: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    summary: str | None = None
    skills: list[str] = Field(default_factory=list)
    roles: list[RoleCreate] = Field(default_factory=list)
    education: list[EducationCreate] = Field(default_factory=list)


class ChatMessageRead(ORMModel):
    id: uuid.UUID
    role: ChatRole
    content: str
    created_at: datetime


class ChatTurnRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)


class ProposedStory(BaseModel):
    """A story the interview suggests recording, pending the user's approval."""

    title: str
    body: str
    role_id: uuid.UUID | None = None
    skills: list[str] = Field(default_factory=list)


class ChatTurnResult(BaseModel):
    """What the model returns for one interview turn."""

    reply: str
    proposed_stories: list[ProposedStory] = Field(default_factory=list)


class ChatTurnResponse(BaseModel):
    reply: ChatMessageRead
    proposed_stories: list[ProposedStory] = Field(default_factory=list)


# ----------------------------------------------------------------------- resume build


class ResumeTemplateBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    sections: list[str] = Field(
        default_factory=lambda: ["summary", "skills", "experience", "education"]
    )
    options: dict = Field(default_factory=dict)

    _sections_null = field_validator("sections", mode="before")(_empty_when_null)
    _options_null = field_validator("options", mode="before")(_empty_dict_when_null)


class ResumeTemplateCreate(ResumeTemplateBase):
    is_default: bool = False


class ResumeTemplateRead(ORMModel, ResumeTemplateBase):
    id: uuid.UUID
    is_default: bool


class TailoredRole(BaseModel):
    """How one existing role should appear on a tailored resume.

    Only the wording is the model's; the role is referenced by id so the company,
    title and dates always come from the record and can never be invented.
    """

    role_id: uuid.UUID
    include: bool = True
    highlights: list[str] = Field(default_factory=list)


class TailoredResume(BaseModel):
    summary: str
    skills: list[str] = Field(default_factory=list)
    roles: list[TailoredRole] = Field(default_factory=list)


class ResumeBuildResult(BaseModel):
    document: "DocumentRead | None" = None
    # The rendered text, so the UI can show it before anything is downloaded.
    preview: str
    tailored: bool


class ResumeBuildRequest(BaseModel):
    application_id: uuid.UUID
    template_id: uuid.UUID | None = None
    export_format: "ExportFormat | None" = None
    # Off by default: a plain render of the record needs no model call.
    tailor: bool = True


class ExportFormat(StrEnum):
    docx = "docx"
    pdf = "pdf"


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


# --------------------------------------------------------------------------- assistant


class MatchAnalysisRequest(BaseModel):
    application_id: uuid.UUID


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
    tone: str = Field(default="professional and direct", max_length=128)
    emphasis: str | None = Field(default=None, max_length=1024)


class InterviewPrepRequest(BaseModel):
    application_id: uuid.UUID
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


ResumeBuildRequest.model_rebuild()
ResumeBuildResult.model_rebuild()


# --------------------------------------------------------------------------- mail


class MailAccountRead(ORMModel):
    id: uuid.UUID
    provider: MailProviderKind
    email_address: str
    status: MailAccountStatus
    last_synced_at: datetime | None = None
    last_sync_error: str | None = None
    last_sync_stats: dict | None = None
    created_at: datetime


class MailStatus(BaseModel):
    """What the mail feature can do right now, so the UI can explain itself."""

    # False when no Google OAuth client (or token key) is configured. Not a
    # transient failure, so the routes say so rather than returning 503.
    configured: bool
    # Whether Claude is available to adjudicate the unclear emails.
    assistant_enabled: bool
    sync_interval_seconds: int
    accounts: list[MailAccountRead]
    pending_suggestions: int


class MailAuthorization(BaseModel):
    authorization_url: str


class MailMessageRead(ORMModel):
    id: uuid.UUID
    from_email: str | None = None
    from_name: str | None = None
    subject: str | None = None
    snippet: str | None = None
    body_text: str | None = None
    received_at: datetime | None = None


class MailSuggestionRead(ORMModel):
    id: uuid.UUID
    application_id: uuid.UUID | None = None
    suggested_status: ApplicationStatus | None = None
    confidence: float
    source: SuggestionSource
    reasoning: str | None = None
    signals: dict | None = None
    state: SuggestionState
    created_at: datetime
    resolved_at: datetime | None = None

    message: MailMessageRead
    # Denormalised for the review list, which would otherwise need a lookup per
    # row to say which job a suggestion is about.
    company_name: str | None = None
    posting_title: str | None = None
    current_status: ApplicationStatus | None = None
    # Which connected mailbox this arrived in. Only interesting once there is
    # more than one, so the UI shows it conditionally.
    account_email: str | None = None


class MailSuggestionAccept(BaseModel):
    """Accept as proposed, or correct it first.

    Both fields override what was suggested -- the reviewer is the authority on
    which application an email belongs to.
    """

    application_id: uuid.UUID | None = None
    status: ApplicationStatus | None = None


class MailSyncResult(BaseModel):
    scanned: int = 0
    stored: int = 0
    suggested: int = 0
    # True when the per-run ceiling cut the run short; syncing again continues.
    truncated: bool = False
    error: str | None = None


class MailVerdict(BaseModel):
    """Claude's read on one email, when the heuristics were not confident.

    The application is named by its position in the candidate list rather than by
    id: a model asked for a UUID will happily produce one that does not exist,
    and an out-of-range index is obvious where an invented id is not.
    """

    application_index: int | None = Field(
        default=None,
        description="0-based index into the candidate list, or null if none of them fit",
    )
    status: ApplicationStatus | None = Field(
        default=None, description="The status this email implies, or null for no change"
    )
    confidence: float = Field(default=0.0, ge=0, le=1)
    reasoning: str = Field(default="", description="One sentence, citing the email's own words")
