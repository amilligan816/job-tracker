"""Deciding what an email means for the pipeline, without a model call.

Two questions, answered separately because they fail differently:

1. *Which application is this about?* Matching on sender domain, company name,
   posting title and thread continuity. Wrong answers here are the expensive
   kind -- a rejection filed against the wrong company -- so the bar is high and
   an unmatched email is dropped rather than guessed at.
2. *What does it say happened?* Weighted phrases per status. English is not
   generous here: "we've decided to move forward with other candidates" is a
   rejection and "we'd love to move forward" is not, so the phrases are specific
   and a bare keyword counts for little.

Everything is deterministic and free. `app/llm.py` can second-guess a low
confidence verdict, but nothing here needs it to work.
"""

import re
import uuid
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.mail.provider import MessageBody, MessageHeader
from app.models import Application, ApplicationStatus, Company, JobPosting, SuggestionSource

# Applicant-tracking systems and recruiting tools. Mail from these is job mail
# even when the sending domain says nothing about the company -- which is the
# normal case, since the ATS sends on the employer's behalf.
ATS_DOMAINS = frozenset(
    {
        "greenhouse.io",
        "greenhouse-mail.io",
        "us.greenhouse-mail.io",
        "lever.co",
        "hire.lever.co",
        "ashbyhq.com",
        "myworkday.com",
        "workday.com",
        "myworkdayjobs.com",
        "smartrecruiters.com",
        "jobvite.com",
        "icims.com",
        "taleo.net",
        "successfactors.com",
        "brassring.com",
        "workable.com",
        "workablemail.com",
        "breezy.hr",
        "recruitee.com",
        "teamtailor.com",
        "bamboohr.com",
        "jazzhr.com",
        "applytojob.com",
        "paylocity.com",
        "rippling.com",
        "gem.com",
        "dover.com",
        "ripplematch.com",
        "hired.com",
        "otta.com",
        "wellfound.com",
        "angel.co",
        "linkedin.com",
        "indeed.com",
        "glassdoor.com",
        "ziprecruiter.com",
    }
)

# Boards that send job *alerts* in bulk. Their mail can still be relevant (an
# employer reply routed through LinkedIn), but an alert digest is not a status
# update, so a List-Id from one of these needs a company match to survive.
BULK_SENDERS = frozenset(
    {"linkedin.com", "indeed.com", "glassdoor.com", "ziprecruiter.com", "otta.com", "wellfound.com"}
)

# Two-label public suffixes we actually meet. Not a full PSL -- the cost of
# getting `co.uk` wrong is a missed match, not a wrong one.
_MULTI_PART_TLDS = frozenset(
    {"co.uk", "org.uk", "ac.uk", "co.jp", "co.nz", "com.au", "com.br", "co.in", "com.sg", "co.za"}
)

_LEGAL_SUFFIXES = re.compile(
    r"\b(?:inc|inc\.|llc|l\.l\.c|ltd|limited|corp|corporation|co|company|gmbh|plc|sa|s\.a|"
    r"bv|b\.v|ab|oy|as|nv|pty|pvt|holdings|group|labs|technologies|technology|software)\b",
    re.IGNORECASE,
)
_NON_WORD = re.compile(r"[^a-z0-9]+")

# A company name shorter than this is too collision-prone to match on text
# alone -- "Box" in a sentence is usually a box.
_MIN_NAME_LEN = 4


# --------------------------------------------------------------- status phrases

# (pattern, weight). Weight is how much the phrase alone should be believed:
# 1.0 is decisive, 0.5 is suggestive, anything lower only breaks ties.
_REJECTION = [
    (r"we (?:have |'ve )?decided to (?:move forward|proceed|continue) with (?:other|another)", 1.0),
    (r"(?:move|moving|going) forward with (?:other|another) candidate", 1.0),
    (r"(?:will |we )?not (?:be )?(?:moving|going) forward", 1.0),
    (r"will not be (?:proceeding|progressing|continuing)", 1.0),
    (r"regret to inform", 1.0),
    (r"pursu(?:e|ing) other candidates", 1.0),
    (r"other candidates whose", 1.0),
    (r"decided not to (?:move|proceed|continue|advance)", 1.0),
    (r"no longer (?:be )?under consideration", 1.0),
    (r"your application (?:was|has been) (?:unsuccessful|declined|rejected)", 1.0),
    (r"(?:we )?(?:won'?t|will not) be (?:able to )?(?:extend|offer)", 1.0),
    (r"(?:position|role|req(?:uisition)?) (?:has been |was )?filled", 0.9),
    (r"not (?:a|the) (?:right|best|ideal) (?:fit|match)", 0.8),
    (r"chosen (?:to move forward with |)another candidate", 1.0),
    (r"\bunfortunately\b", 0.5),
    (r"\bregrettably\b", 0.5),
]

_OFFER = [
    (r"(?:pleased|delighted|excited|happy|thrilled) to (?:offer|extend)", 1.0),
    (r"offer of employment", 1.0),
    (r"(?:formal|written|official) offer", 1.0),
    (r"offer letter", 1.0),
    (r"extend(?:ing)? (?:you )?an offer", 1.0),
    (r"compensation package", 0.5),
]

_INTERVIEWING = [
    (r"invit(?:e|ing) you to (?:an?n? )?(?:interview|onsite|on-site|final)", 1.0),
    (r"schedul(?:e|ing) (?:an?|your|the) (?:interview|onsite|on-site|technical)", 1.0),
    (r"(?:technical|onsite|on-site|final|panel|virtual|second|third) interview", 0.9),
    (r"interview (?:loop|panel|process|round)", 0.8),
    (r"next (?:round|stage|step) (?:of|in) (?:the|our)", 0.8),
    (r"take[- ]home (?:assignment|exercise|challenge|project)", 0.9),
    (r"coding (?:challenge|exercise|assessment|interview)", 0.9),
    (r"\binterview\b", 0.4),
]

_SCREENING = [
    (
        r"(?:recruiter|phone|initial|intro(?:ductory)?|screening) "
        r"(?:screen|call|chat|conversation)",
        1.0,
    ),
    (r"(?:set up|schedule|find|book) (?:a |some )?time to (?:chat|talk|connect|speak)", 0.9),
    (r"would (?:love|like) to (?:chat|connect|speak|learn more)", 0.8),
    (r"(?:quick|brief|short) (?:call|chat)", 0.7),
    (r"reach(?:ing)? out (?:about|regarding) your application", 0.7),
    (r"your (?:application|profile) caught (?:our|my) (?:eye|attention)", 0.7),
    (r"mov(?:e|ing) (?:you )?(?:forward|to the next)", 0.6),
]

_APPLIED = [
    (r"(?:we(?:'ve| have)? )?received your application", 1.0),
    (r"application (?:has been |was )?(?:received|submitted)", 1.0),
    (r"thank(?:s| you) for (?:applying|your application)", 0.9),
    (r"thank(?:s| you) for your interest in", 0.6),
    (r"we(?:'ve| have) got your application", 0.9),
]

_PHRASES: dict[ApplicationStatus, list[tuple[re.Pattern, float]]] = {
    ApplicationStatus.rejected: [(re.compile(p, re.IGNORECASE), w) for p, w in _REJECTION],
    ApplicationStatus.offer: [(re.compile(p, re.IGNORECASE), w) for p, w in _OFFER],
    ApplicationStatus.interviewing: [(re.compile(p, re.IGNORECASE), w) for p, w in _INTERVIEWING],
    ApplicationStatus.screening: [(re.compile(p, re.IGNORECASE), w) for p, w in _SCREENING],
    ApplicationStatus.applied: [(re.compile(p, re.IGNORECASE), w) for p, w in _APPLIED],
}

# Ties break toward the more consequential reading -- a maybe-rejection is worth
# surfacing, a maybe-acknowledgement is not.
_PRECEDENCE = [
    ApplicationStatus.rejected,
    ApplicationStatus.offer,
    ApplicationStatus.interviewing,
    ApplicationStatus.screening,
    ApplicationStatus.applied,
]

# How far along each status is. A suggestion that moves an application backwards
# is dropped: an autoresponder arriving after a phone screen does not undo it.
_PROGRESS = {
    ApplicationStatus.saved: 0,
    ApplicationStatus.applied: 1,
    ApplicationStatus.screening: 2,
    ApplicationStatus.interviewing: 3,
    ApplicationStatus.offer: 4,
    ApplicationStatus.accepted: 5,
    ApplicationStatus.rejected: 5,
    ApplicationStatus.withdrawn: 5,
}
_TERMINAL = {ApplicationStatus.accepted, ApplicationStatus.rejected, ApplicationStatus.withdrawn}

# Only this much of a body is scanned. Status language is at the top; the rest is
# signatures, legal boilerplate and quoted history that only adds false hits.
BODY_SCAN_CHARS = 6000


# ------------------------------------------------------------------- data shapes


@dataclass(slots=True)
class ApplicationTarget:
    """One tracked application, reduced to what identifies it in an inbox."""

    application_id: uuid.UUID
    status: ApplicationStatus
    company_name: str | None = None
    company_domain: str | None = None
    posting_domain: str | None = None
    title: str | None = None

    @property
    def name_token(self) -> str | None:
        return _normalize_name(self.company_name)


@dataclass(slots=True)
class Verdict:
    application_id: uuid.UUID | None = None
    suggested_status: ApplicationStatus | None = None
    confidence: float = 0.0
    reasoning: str = ""
    signals: dict = field(default_factory=dict)
    source: SuggestionSource = SuggestionSource.heuristic


# ------------------------------------------------------------------ target build


async def build_targets(db: AsyncSession) -> list[ApplicationTarget]:
    """Every application worth matching mail against.

    Includes the closed ones: a rejection can arrive after you have already
    withdrawn, and filing it against the right row still beats dropping it.
    """
    result = await db.execute(
        select(Application).options(
            selectinload(Application.posting).selectinload(JobPosting.company)
        )
    )
    targets = []
    for application in result.scalars().all():
        posting: JobPosting | None = application.posting
        company: Company | None = posting.company if posting else None
        targets.append(
            ApplicationTarget(
                application_id=application.id,
                status=application.status,
                company_name=company.name if company else None,
                company_domain=_domain_of(company.website) if company else None,
                posting_domain=_domain_of(posting.source_url) if posting else None,
                title=posting.title if posting else None,
            )
        )
    return targets


# ---------------------------------------------------------------------- stage one


def is_worth_reading(
    header: MessageHeader,
    targets: list[ApplicationTarget],
    thread_application: uuid.UUID | None = None,
) -> bool:
    """Whether this message earns a body fetch.

    Sender and subject only. Most of an inbox dies here, which is the point --
    bodies are a request each, and mail we will never link is mail we should
    never download.
    """
    if thread_application is not None:
        return True

    domain = _domain_of_email(header.from_email)
    haystack = " ".join(filter(None, (header.from_name, header.subject))).lower()
    company_hit = any(
        _mentions(haystack, t.name_token)
        or (t.company_domain and domain == t.company_domain)
        or (t.posting_domain and domain == t.posting_domain)
        or _mentions(haystack, _normalize_name(t.title), min_len=8)
        for t in targets
    )
    if company_hit:
        return True

    if domain in ATS_DOMAINS:
        # A job-board digest names dozens of companies we do not track. Without a
        # company hit, bulk mail from a board is noise.
        return not (header.list_id and domain in BULK_SENDERS)
    return False


# ---------------------------------------------------------------------- stage two


def classify(
    header: MessageHeader,
    body: MessageBody,
    targets: list[ApplicationTarget],
    thread_application: uuid.UUID | None = None,
) -> Verdict | None:
    """Link a message to an application and read a status out of it.

    Returns None when nothing plausible matched -- the caller drops the message
    rather than storing it.
    """
    match, match_signals = _match_application(header, body, targets, thread_application)
    if match is None:
        return None

    status, status_conf, status_signals = _read_status(header, body)
    suggested = guard_transition(match.status, status)

    signals = {**match_signals, **status_signals}
    if suggested is None:
        return Verdict(
            application_id=match.application_id,
            suggested_status=None,
            # Half weight: we are confident it is *about* this application, and
            # making no claim about what it means.
            confidence=round(match_signals["match_confidence"] * 0.5, 3),
            reasoning=_no_change_reason(match.status, status),
            signals=signals,
        )

    confidence = round(match_signals["match_confidence"] * status_conf, 3)
    return Verdict(
        application_id=match.application_id,
        suggested_status=suggested,
        confidence=confidence,
        reasoning=_reason(match, suggested, status_signals),
        signals=signals,
    )


def _match_application(
    header: MessageHeader,
    body: MessageBody,
    targets: list[ApplicationTarget],
    thread_application: uuid.UUID | None,
) -> tuple[ApplicationTarget | None, dict]:
    if thread_application is not None:
        target = next((t for t in targets if t.application_id == thread_application), None)
        if target is not None:
            return target, {"match_confidence": 1.0, "matched_on": ["earlier mail in this thread"]}

    scored = _score_targets(header, body, targets)
    if not scored:
        return None, {}

    best_score, best_hits, best = scored[0]
    runner_up = scored[1][0] if len(scored) > 1 else 0.0

    # Below this, the only evidence is a stray mention -- not enough to file mail
    # against someone's pipeline.
    if best_score < 0.45:
        return None, {}
    # Two applications matching almost equally well (same company, two roles)
    # means we cannot say which, and a coin flip is worse than nothing.
    if runner_up and best_score - runner_up < 0.15:
        return None, {}

    return best, {"match_confidence": round(min(1.0, best_score), 3), "matched_on": best_hits}


def _score_targets(
    header: MessageHeader, body: MessageBody, targets: list[ApplicationTarget]
) -> list[tuple[float, list[str], ApplicationTarget]]:
    """Rank every application by how much of this email points at it.

    Returned highest first, with the reasons, so both the strict matcher and the
    Claude shortlist work off one set of rules.
    """
    domain = _domain_of_email(header.from_email)
    subject = (header.subject or "").lower()
    from_name = (header.from_name or "").lower()
    body_text = (body.body_text or body.snippet or "")[:BODY_SCAN_CHARS].lower()

    scored: list[tuple[float, list[str], ApplicationTarget]] = []
    for target in targets:
        score = 0.0
        hits: list[str] = []
        name = target.name_token
        title = _normalize_name(target.title)

        if domain and target.company_domain and domain == target.company_domain:
            score += 0.55
            hits.append(f"sender domain is {domain}")
        elif domain and target.posting_domain and domain == target.posting_domain:
            score += 0.45
            hits.append(f"sender domain matches the posting link ({domain})")

        if _mentions(from_name, name):
            score += 0.45
            hits.append(f"sender name mentions {target.company_name}")
        elif (
            domain in ATS_DOMAINS and name and name in _NON_WORD.sub("", (header.from_email or ""))
        ):
            score += 0.4
            hits.append(f"{target.company_name} in the applicant-tracking sender address")

        if _mentions(subject, name):
            score += 0.35
            hits.append(f"subject mentions {target.company_name}")
        elif _mentions(body_text, name):
            score += 0.2
            hits.append(f"body mentions {target.company_name}")

        if _mentions(subject, title, min_len=8):
            score += 0.3
            hits.append(f'subject mentions "{target.title}"')
        elif _mentions(body_text, title, min_len=8):
            score += 0.15
            hits.append(f'body mentions "{target.title}"')

        if score > 0:
            scored.append((score, hits, target))

    scored.sort(key=lambda row: row[0], reverse=True)
    return scored


def _read_status(
    header: MessageHeader, body: MessageBody
) -> tuple[ApplicationStatus | None, float, dict]:
    text = "\n".join(
        filter(None, (header.subject, (body.body_text or body.snippet or "")[:BODY_SCAN_CHARS]))
    )
    if not text.strip():
        return None, 0.0, {}

    totals: dict[ApplicationStatus, float] = {}
    matched: dict[str, list[str]] = {}
    for status, patterns in _PHRASES.items():
        weight = 0.0
        phrases: list[str] = []
        for pattern, pattern_weight in patterns:
            found = pattern.search(text)
            if found:
                weight += pattern_weight
                phrases.append(found.group(0).strip().lower())
        if weight:
            totals[status] = weight
            matched[status.value] = phrases

    if not totals:
        return None, 0.0, {}

    # A decisive rejection outranks everything else present. Rejections routinely
    # thank you for interviewing and mention the offer they are not making, so
    # the highest raw total would often be the wrong read.
    rejection = totals.get(ApplicationStatus.rejected, 0.0)
    if rejection >= 1.0:
        best = ApplicationStatus.rejected
    else:
        top = max(totals.values())
        best = next(s for s in _PRECEDENCE if totals.get(s, 0.0) == top)

    # One decisive phrase is enough to be sure; corroborating phrases add a
    # little, and nothing gets past 1.0.
    confidence = min(1.0, 0.55 + 0.25 * totals[best])
    return best, round(confidence, 3), {"phrases": matched, "read_as": best.value}


def guard_transition(
    current: ApplicationStatus, suggested: ApplicationStatus | None
) -> ApplicationStatus | None:
    """Drop suggestions that would not be an update.

    Three cases: nothing was read; the application is already where the email
    says; or the email would drag it backwards -- an ATS autoresponder landing
    after a phone screen does not un-screen you. A closed application stays
    closed unless a *different* closing arrives, which is worth a look.
    """
    if suggested is None or suggested == current:
        return None
    if current in _TERMINAL:
        return suggested if suggested in _TERMINAL else None
    if _PROGRESS[suggested] <= _PROGRESS[current]:
        return None
    return suggested


def _reason(target: ApplicationTarget, status: ApplicationStatus, signals: dict) -> str:
    phrases = signals.get("phrases", {}).get(status.value, [])
    quoted = ", ".join(f'"{p}"' for p in phrases[:3])
    where = target.company_name or "this application"
    return f"Reads as {status.value} for {where}" + (f" — matched {quoted}" if quoted else "")


def _no_change_reason(current: ApplicationStatus, read: ApplicationStatus | None) -> str:
    if read is None:
        return "Related mail, but nothing in it reads as a status change."
    if read == current:
        return f"Reads as {read.value}, which is where this application already is."
    return (
        f"Reads as {read.value}, which would move this application backwards from {current.value}."
    )


# ----------------------------------------------------------------------- helpers


def _normalize_name(value: str | None) -> str | None:
    """Reduce a company or role name to a token we can look for in prose."""
    if not value:
        return None
    stripped = _LEGAL_SUFFIXES.sub(" ", value.lower())
    token = _NON_WORD.sub("", stripped)
    return token or None


def _mentions(haystack: str, needle: str | None, min_len: int = _MIN_NAME_LEN) -> bool:
    """Whether `haystack` contains `needle`, comparing on letters and digits only.

    Punctuation and spacing vary too much between a display name, a subject line
    and a database row to compare literally -- "Acme, Inc." and "acme" should
    meet. Short needles are refused outright; they collide with ordinary words.
    """
    if not needle or len(needle) < min_len or not haystack:
        return False
    return needle in _NON_WORD.sub("", haystack)


def _domain_of(url: str | None) -> str | None:
    if not url:
        return None
    candidate = url if "//" in url else f"//{url}"
    host = (urlsplit(candidate).hostname or "").lower()
    return _registrable(host) if host else None


def _domain_of_email(address: str | None) -> str | None:
    if not address or "@" not in address:
        return None
    return _registrable(address.rsplit("@", 1)[1].lower())


def _registrable(host: str) -> str | None:
    """Trim a host to the part that identifies who sent it.

    `careers.mail.acme.com` and `acme.com` are the same company; the bounce
    subdomains ATS vendors use should not read as different senders.
    """
    host = host.removeprefix("www.").strip(".")
    labels = host.split(".")
    if len(labels) < 2:
        return host or None
    tail = ".".join(labels[-2:])
    if tail in _MULTI_PART_TLDS and len(labels) >= 3:
        return ".".join(labels[-3:])
    return tail


def shortlist(
    header: MessageHeader,
    body: MessageBody,
    targets: list[ApplicationTarget],
    limit: int = 8,
) -> list[ApplicationTarget]:
    """The applications an email could plausibly be about.

    Looser than `classify` on purpose: this is what gets handed to Claude when
    the strict matcher was not confident, and the model is better placed than a
    regex to tell two near-misses apart. When nothing scores at all -- an ATS
    sending from a domain we do not recognise -- the open applications stand in,
    since one of them is the likely subject.
    """
    scored = _score_targets(header, body, targets)
    if scored:
        return [target for _, _, target in scored[:limit]]
    return [t for t in targets if t.status not in _TERMINAL][:limit]


def describe(target: ApplicationTarget) -> str:
    """One line naming an application, for the model's candidate list."""
    parts = [target.title or "(untitled role)"]
    if target.company_name:
        parts.append(f"at {target.company_name}")
    parts.append(f"— currently {target.status.value}")
    return " ".join(parts)
