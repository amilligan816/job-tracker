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
from app.schemas import ExtractedPosting, MatchAnalysis

logger = logging.getLogger(__name__)

# Opus 5 runs adaptive thinking when `thinking` is omitted; effort is what we tune.
EXTRACTION_MAX_TOKENS = 8000
ANALYSIS_MAX_TOKENS = 32000
# Postings and resumes are long but bounded; this keeps a pathological upload
# from turning into an expensive request.
MAX_CONTEXT_CHARS = 120_000


class AssistantUnavailable(RuntimeError):
    """No API key configured, or Claude declined the request."""


@dataclass(slots=True)
class Usage:
    input_tokens: int | None = None
    output_tokens: int | None = None


@lru_cache
def _client() -> anthropic.AsyncAnthropic:
    settings = get_settings()
    if not settings.assistant_enabled:
        raise AssistantUnavailable(
            "Assistant features need ANTHROPIC_API_KEY to be set in the environment."
        )
    return anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)


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


def _guard_refusal(response) -> None:
    if getattr(response, "stop_reason", None) == "refusal":
        details = getattr(response, "stop_details", None)
        category = getattr(details, "category", None)
        logger.warning("Claude declined the request (category=%s)", category)
        raise AssistantUnavailable("Claude declined to answer this request.")


def _text_of(response) -> str:
    return "\n".join(block.text for block in response.content if block.type == "text").strip()


async def _generate(system: str, prompt: str, max_tokens: int = ANALYSIS_MAX_TOKENS):
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
"hybrid" if it names both, "onsite" if it requires presence, else "unknown"."""


async def extract_posting(raw_text: str) -> tuple[ExtractedPosting, Usage]:
    """Pull structured fields out of a raw posting blob."""
    response = await _client().messages.parse(
        model=_model(),
        max_tokens=EXTRACTION_MAX_TOKENS,
        system=_EXTRACT_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": f"Extract the structured posting data:\n\n{_clip(raw_text)}",
            }
        ],
        output_format=ExtractedPosting,
    )
    _guard_refusal(response)
    return response.parsed_output, _usage(response)


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
        max_tokens=ANALYSIS_MAX_TOKENS,
        system=_MATCH_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        output_format=MatchAnalysis,
    )
    _guard_refusal(response)
    return response.parsed_output, _usage(response)


# ---------------------------------------------------------------------- cover letter

_COVER_LETTER_SYSTEM = """You draft cover letters for a candidate.

- Ground every claim in the resume. If the resume does not support a claim, leave \
it out -- do not invent employers, dates, metrics, or credentials.
- Four short paragraphs at most. No restating the resume line by line.
- Open with the specific reason this role fits, not "I am writing to apply".
- Plain text, no markdown headers, no placeholder brackets unless a fact is \
genuinely missing -- then use [SQUARE BRACKETS] so the candidate can spot it."""


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

_INTERVIEW_SYSTEM = """You prepare a candidate for a specific interview round.

Produce markdown with these sections:
- **Likely questions** -- 8-12, drawn from the posting's actual requirements, each \
with a one-line note on what the interviewer is really checking.
- **Your strongest stories** -- map real resume experience to those questions, in \
situation/action/result shape.
- **Where you are thin** -- gaps the interviewer may probe, and an honest way to \
handle each.
- **Questions to ask them** -- 5, specific to this company and role.

Use only resume facts. Never fabricate experience."""


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
    response = await _generate(_INTERVIEW_SYSTEM, prompt)
    return _text_of(response), _usage(response)
