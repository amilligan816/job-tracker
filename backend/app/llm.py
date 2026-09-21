"""Claude-backed assistant features.

One client, three jobs: structure a raw posting, compare a resume against a
posting, and draft candidate-facing text. Everything here is optional -- with no
ANTHROPIC_API_KEY set, `AssistantUnavailable` is raised and the routers turn it
into a 503 so the rest of the app keeps working.
"""

import logging
from dataclasses import dataclass
from functools import lru_cache

import anthropic

from app.config import get_settings
from app.schemas import (
    ChatTurnResult,
    ExtractedPosting,
    ImportedExperience,
    MailVerdict,
    MatchAnalysis,
    TailoredResume,
)

logger = logging.getLogger(__name__)

# Opus 5 runs adaptive thinking when `thinking` is omitted; effort is what we tune.
# Non-streaming requests have a ceiling: the SDK refuses a `max_tokens` large
# enough that the call could exceed its 10-minute timeout. Structured outputs
# here are bounded and nowhere near these limits -- the budgets exist to catch a
# runaway, not to be spent.
EXTRACTION_MAX_TOKENS = 8000
STRUCTURED_MAX_TOKENS = 8000
# A full career history is longer than a posting; still under the ceiling.
IMPORT_MAX_TOKENS = 16000
# Free-form prose is streamed, so it can have real room.
GENERATION_MAX_TOKENS = 32000
# Postings and resumes are long but bounded; this keeps a pathological upload
# from turning into an expensive request.
MAX_CONTEXT_CHARS = 120_000

_LISTED_VS_EVIDENCED = """
A skill that appears only in a skills list is a listed skill, not a
demonstrated one. Never upgrade it into a claim of depth, frequency or
recency -- no "I write X daily", no "extensive experience with X" -- unless a
role or story actually shows it. Where the record only lists something, either
say nothing about it or be accurate about what it is."""


class AssistantUnavailable(RuntimeError):
    """No API key configured, or Claude declined the request."""


@dataclass(slots=True)
class Usage:
    input_tokens: int | None = None
    output_tokens: int | None = None


@lru_cache
def _client() -> anthropic.AsyncAnthropic:
    """Build the client from whichever credential is configured.

    The SDK resolves credentials in its own order -- api key, auth token, then
    an `ant auth login` profile or workload identity on disk -- so with
    `ANTHROPIC_AMBIENT_AUTH` set we hand it nothing and let it look.
    """
    settings = get_settings()
    if not settings.assistant_enabled:
        raise AssistantUnavailable(
            "Assistant features need a credential: set ANTHROPIC_API_KEY (or "
            "ANTHROPIC_AUTH_TOKEN, or ANTHROPIC_AMBIENT_AUTH=true) in the environment."
        )

    if settings.anthropic_api_key:
        return anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    if settings.anthropic_auth_token:
        return anthropic.AsyncAnthropic(auth_token=settings.anthropic_auth_token)
    return anthropic.AsyncAnthropic()


def _model() -> str:
    return get_settings().anthropic_model


def _clip(text: str | None, limit: int = MAX_CONTEXT_CHARS) -> str:
    """Trim oversized context at a marked boundary rather than silently.

    Nothing here should normally hit the limit; when it does, the marker tells
    both the model and a human reader that the tail is missing.
    """
    if not text:
        return "(not provided)"
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n[...truncated for length...]"


def _usage(response) -> Usage:
    usage = getattr(response, "usage", None)
    if usage is None:
        return Usage()
    return Usage(
        input_tokens=getattr(usage, "input_tokens", None),
        output_tokens=getattr(usage, "output_tokens", None),
    )


def _strict_schema(model_cls) -> dict:
    """A Pydantic model as a schema strict tool use will accept.

    Every object -- including nested ones under `$defs` -- needs
    `additionalProperties: false` and an explicit `required` list, or the API
    rejects the whole tool. Optional fields stay in `required`; their schema
    already permits null, so the model can still say "not stated".
    """

    def harden(node) -> None:
        if isinstance(node, dict):
            if "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"])
            for value in node.values():
                harden(value)
        elif isinstance(node, list):
            for item in node:
                harden(item)

    schema = model_cls.model_json_schema()
    harden(schema)
    return schema


async def _extract_via_tool(model_cls, system, prompt: str, max_tokens: int):
    """Structured extraction through a strict tool instead of `output_format`.

    `output_format` has a tighter schema budget and rejects our larger
    extraction shapes with "Schema is too complex"; a strict tool accepts the
    same schema and still guarantees the input validates. Smaller schemas
    elsewhere keep using `messages.parse`, which is simpler.
    """
    name = f"record_{model_cls.__name__.lower()}"
    response = await _client().messages.create(
        model=_model(),
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
        tools=[
            {
                "name": name,
                "description": f"Record the extracted {model_cls.__name__}.",
                "strict": True,
                "input_schema": _strict_schema(model_cls),
            }
        ],
        # Forcing the tool keeps the model from answering in prose. Note this
        # form is rejected by Fable 5.1 / Mythos 5.1, which would need
        # tool_choice "auto" plus an instruction naming the tool.
        tool_choice={"type": "tool", "name": name},
    )
    _guard_refusal(response)

    block = next((b for b in response.content if b.type == "tool_use"), None)
    if block is None:
        raise AssistantUnavailable("Claude returned no structured data for this request.")
    if response.stop_reason == "max_tokens":
        raise AssistantUnavailable(
            "The response was cut off before it finished. Try a shorter document."
        )
    return model_cls.model_validate(block.input), _usage(response)


def _guard_refusal(response) -> None:
    if getattr(response, "stop_reason", None) == "refusal":
        details = getattr(response, "stop_details", None)
        category = getattr(details, "category", None)
        logger.warning("Claude declined the request (category=%s)", category)
        raise AssistantUnavailable("Claude declined to answer this request.")


def _text_of(response) -> str:
    return "\n".join(block.text for block in response.content if block.type == "text").strip()


async def _generate(system: str, prompt: str, max_tokens: int = GENERATION_MAX_TOKENS):
    """Single-turn text generation.

    Streamed: adaptive thinking plus a large `max_tokens` can run long enough to
    trip the SDK's non-streaming HTTP timeout.
    """
    async with _client().messages.stream(
        model=_model(),
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        response = await stream.get_final_message()

    _guard_refusal(response)
    return response


# --------------------------------------------------------------- experience extraction

_IMPORT_SYSTEM = """You convert a resume into structured career data.

Rules:
- Transcribe, do not embellish. Every role, date, and achievement must come
  from the document. Never invent an employer, a metric, or a date.
- Keep each highlight as one achievement, in the candidate's own words where
  the resume already reads well.
- Dates: use the first of the month when only a month and year are given.
  Leave `end_date` null for a current role.
- If the resume genuinely does not state something, leave it null or empty
  rather than guessing."""


async def extract_experience(resume_text: str) -> tuple[ImportedExperience, Usage]:
    """Pull structured career data out of an uploaded resume for review."""
    return await _extract_via_tool(
        ImportedExperience,
        _IMPORT_SYSTEM,
        f"Extract the structured career data:\n\n{_clip(resume_text)}",
        IMPORT_MAX_TOKENS,
    )


# ------------------------------------------------------------------ experience interview

_EXPERIENCE_INTERVIEW_SYSTEM = """You are interviewing a candidate to draw out the detail
their resume has no room for. That detail is what later makes a cover letter
specific and an interview answer real.

How to work:
- Ask ONE question at a time, and make it concrete. "What was the hardest part
  of that migration?" beats "tell me about your experience".
- Follow the thread. Chase scope, constraints, the decision they made and why,
  what went wrong, and what they would do differently.
- Push gently for numbers, team sizes, timelines and outcomes -- but never
  supply them yourself, and never treat a guess as a fact.
- When a complete story has emerged, propose it in `proposed_stories`. A story
  is complete when it has a situation, what they actually did, and an outcome.
  Write it in their voice, using only what they told you.
- Do not propose a story for every message. Most turns should be an empty list
  and another question.
- Keep replies short. You are interviewing, not lecturing."""


async def interview_turn(
    experience: str,
    history: list[dict],
    message: str,
) -> tuple[ChatTurnResult, Usage]:
    """One turn of the experience interview.

    The record goes in the system prompt behind a cache breakpoint: it is stable
    across a conversation, so every turn after the first reads it from cache
    instead of paying for it again.
    """
    system = [
        {"type": "text", "text": _EXPERIENCE_INTERVIEW_SYSTEM},
        {
            "type": "text",
            "text": f"The candidate's record so far:\n\n{_clip(experience)}",
            "cache_control": {"type": "ephemeral"},
        },
    ]
    response = await _client().messages.parse(
        model=_model(),
        max_tokens=STRUCTURED_MAX_TOKENS,
        system=system,
        messages=[*history, {"role": "user", "content": message}],
        output_format=ChatTurnResult,
    )
    _guard_refusal(response)
    return response.parsed_output, _usage(response)


# --------------------------------------------------------------------- resume tailoring

_TAILOR_SYSTEM = (
    """You tailor a candidate's resume to one job posting.

You are selecting and sharpening, not writing new history:
- Every highlight must be traceable to something in the record. Rephrase for
  emphasis and brevity; never add a metric, a technology, or a responsibility
  that is not there.
- Reference each role by its `role_id` exactly as given. Do not restate the
  company, title or dates -- those come from the record, not from you.
- Set `include: false` for a role that earns no space on this application, but
  keep the recent and relevant ones even if the fit is partial. Never drop a
  role in a way that creates an unexplained gap in the last ten years.
- Order highlights within a role by relevance to this posting, strongest first,
  and stay within the requested maximum.
- Each role's own summary line is rendered above its bullets. Do not repeat it
  as a highlight -- the bullets should add to it, not restate it.
- The summary is two or three sentences, specific to this role, and must not
  claim anything the record does not support.
"""
    + _LISTED_VS_EVIDENCED
)


async def tailor_resume(
    experience: str,
    posting_text: str,
    role_catalogue: str,
    max_highlights: int,
) -> tuple[TailoredResume, Usage]:
    """Choose and sharpen what goes on the resume for one posting."""
    system = [
        {"type": "text", "text": _TAILOR_SYSTEM},
        {
            "type": "text",
            "text": f"The candidate's full record:\n\n{_clip(experience)}",
            "cache_control": {"type": "ephemeral"},
        },
    ]
    prompt = (
        f"Roles you may include, with their ids:\n{role_catalogue}\n\n"
        f"At most {max_highlights} highlights per role.\n\n"
        f"JOB POSTING\n-----------\n{_clip(posting_text)}\n\n"
        "Produce the tailored resume."
    )
    response = await _client().messages.parse(
        model=_model(),
        max_tokens=STRUCTURED_MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": prompt}],
        output_format=TailoredResume,
    )
    _guard_refusal(response)
    return response.parsed_output, _usage(response)


# ----------------------------------------------------------------- posting extraction

_EXTRACT_SYSTEM = """You extract structured data from job postings.

Rules:
- Use only what the posting states. Never infer a salary, a location, or a \
seniority level that is not written down.
- Leave a field null when the posting does not say. An empty list is the right \
answer for a section the posting omits.
- Keep list items short -- one requirement or responsibility per item, in the \
posting's own words where possible.
- `remote_type` is "remote" only if the role can be done fully remotely, \
"hybrid" if it names both, "onsite" if it requires presence, else "unknown".
- Set `is_job_posting` false when the text is not a posting at all: a careers \
page that lists no role, navigation and cookie/EEO boilerplate with no job in \
it, a search results page, a login wall, an error page. Say so instead of \
assembling a posting out of the page furniture -- an invented posting is worse \
than none, because it looks real. When it is false, use `title` to say briefly \
what the text actually was and leave the other fields empty."""


async def extract_posting(raw_text: str) -> tuple[ExtractedPosting, Usage]:
    """Pull structured fields out of a raw posting blob."""
    return await _extract_via_tool(
        ExtractedPosting,
        _EXTRACT_SYSTEM,
        f"Extract the structured posting data:\n\n{_clip(raw_text)}",
        EXTRACTION_MAX_TOKENS,
    )


# -------------------------------------------------------------------- match analysis

_MATCH_SYSTEM = """You advise a candidate on how well their resume matches a job \
posting.

Be specific and honest. A gap the candidate does not have is more useful to them \
than an inflated score.

- `overall_fit` is 0-100. Reserve 80+ for a resume that already evidences most \
hard requirements.
- Every strength must cite something actually on the resume.
- For each gap, set `severity` to "blocking", "significant", or "minor", and put \
any partial/adjacent experience in `evidence` (null if there is none).
- `resume_suggestions` are concrete edits to the existing resume -- rephrasings \
and reorderings of real experience, never invented experience.
- `talking_points` are things to raise in a screen."""


async def analyze_match(posting_text: str, resume_text: str | None) -> tuple[MatchAnalysis, Usage]:
    prompt = (
        f"JOB POSTING\n-----------\n{_clip(posting_text)}\n\n"
        f"CANDIDATE RESUME\n----------------\n{_clip(resume_text)}"
    )
    response = await _client().messages.parse(
        model=_model(),
        max_tokens=STRUCTURED_MAX_TOKENS,
        system=_MATCH_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        output_format=MatchAnalysis,
    )
    _guard_refusal(response)
    return response.parsed_output, _usage(response)


# ---------------------------------------------------------------------- cover letter


_COVER_LETTER_SYSTEM = (
    """You draft cover letters for a candidate.

- Ground every claim in the resume. If the resume does not support a claim, leave \
it out -- do not invent employers, dates, metrics, or credentials.
- Four short paragraphs at most. No restating the resume line by line.
- Open with the specific reason this role fits, not "I am writing to apply".
- Plain text, no markdown headers, no placeholder brackets unless a fact is \
genuinely missing -- then use [SQUARE BRACKETS] so the candidate can spot it."""
    + _LISTED_VS_EVIDENCED
)


async def draft_cover_letter(
    posting_text: str,
    resume_text: str | None,
    company_name: str | None,
    tone: str,
    emphasis: str | None,
) -> tuple[str, Usage]:
    prompt = (
        f"Company: {company_name or 'unknown'}\n"
        f"Requested tone: {tone}\n"
        f"Points to emphasise: {emphasis or 'none specified'}\n\n"
        f"JOB POSTING\n-----------\n{_clip(posting_text)}\n\n"
        f"CANDIDATE RESUME\n----------------\n{_clip(resume_text)}\n\n"
        "Draft the cover letter."
    )
    response = await _generate(_COVER_LETTER_SYSTEM, prompt)
    return _text_of(response), _usage(response)


# --------------------------------------------------------------------- interview prep

_INTERVIEW_PREP_SYSTEM = (
    """You prepare a candidate for a specific interview round.

Produce markdown with these sections:
- **Likely questions** -- 8-12, drawn from the posting's actual requirements,
  each with a one-line note on what the interviewer is really checking.
- **Your strongest stories** -- map real experience to those questions, in
  situation/action/result shape.
- **Where you are thin** -- gaps the interviewer may probe, and an honest way
  to handle each.
- **Questions to ask them** -- 5, specific to this company and role.

Use only what the record contains. Never fabricate experience."""
    + _LISTED_VS_EVIDENCED
)


async def draft_interview_prep(
    posting_text: str,
    resume_text: str | None,
    company_name: str | None,
    round_type: str,
) -> tuple[str, Usage]:
    prompt = (
        f"Company: {company_name or 'unknown'}\n"
        f"Interview round: {round_type}\n\n"
        f"JOB POSTING\n-----------\n{_clip(posting_text)}\n\n"
        f"CANDIDATE RESUME\n----------------\n{_clip(resume_text)}\n\n"
        "Write the prep document."
    )
    response = await _generate(_INTERVIEW_PREP_SYSTEM, prompt)
    return _text_of(response), _usage(response)


# ------------------------------------------------------------------- mail triage

_MAIL_SYSTEM = """You read one email and say what it means for a job application.

You are the second opinion. Simple string matching already ran and was not \
confident, which usually means the email is either ambiguous or phrased in a way \
the phrase list does not cover.

- Pick the candidate application the email is about by its index. If none of \
them fit -- it is a job alert, a newsletter, an unrelated recruiter cold \
email -- return null. A wrong match is worse than no match.
- `status` is what the email says *has happened*, not what the candidate hopes. \
Return null when the email carries no status change: acknowledgements of an \
application already known to be submitted, scheduling logistics for an interview \
already recorded, and general recruiter chatter are all null.
- A rejection is a rejection however warmly it is phrased. "We've decided to \
move forward with other candidates" is `rejected`.
- An invitation to talk to a recruiter is `screening`. An invitation to a \
technical, panel, or onsite interview is `interviewing`.
- `confidence` is how sure you are, 0 to 1. Be honest; a 0.4 that is right is \
more useful than a 0.9 that is guessed.
- `reasoning` is one sentence quoting the email's own words."""


async def classify_email(
    *,
    subject: str | None,
    sender: str | None,
    body: str | None,
    candidates: list[str],
) -> tuple[MailVerdict, Usage]:
    """Adjudicate one email against a shortlist of applications.

    `candidates` are pre-rendered one-line descriptions; the model answers with
    an index into this list, so it cannot name an application that isn't there.
    """
    listing = "\n".join(f"[{i}] {line}" for i, line in enumerate(candidates)) or "(none)"
    prompt = (
        f"CANDIDATE APPLICATIONS\n----------------------\n{listing}\n\n"
        f"EMAIL\n-----\nFrom: {sender or '(unknown)'}\n"
        f"Subject: {subject or '(no subject)'}\n\n{_clip(body, 20_000)}"
    )
    response = await _client().messages.parse(
        model=_model(),
        max_tokens=EXTRACTION_MAX_TOKENS,
        system=_MAIL_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        output_format=MailVerdict,
    )
    _guard_refusal(response)
    return response.parsed_output, _usage(response)
