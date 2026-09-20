"""Deterministic resume-to-posting match rating.

No model call: both sides are already stored as plain text, so the score is pure
string matching over a skill vocabulary plus a years-of-experience comparison.
That makes it instant, free, and identical every time it runs -- which is what
you want for a number shown on every row of a list.

It gets sharper when Claude has extracted a posting (requirements are weighted
above passing mentions), but it never depends on that having happened.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache

from app.skills import AMBIGUOUS_ALIASES, SKILLS

# Weights by where a skill showed up. A hard requirement should move the score
# more than a technology named once in a benefits paragraph.
WEIGHT_REQUIRED = 3
WEIGHT_STACK = 2
WEIGHT_NICE_TO_HAVE = 1
WEIGHT_MENTIONED = 1

# How much of the final score each signal carries when both are available.
COVERAGE_SHARE = 0.8
EXPERIENCE_SHARE = 0.2

# Below this many recognised posting skills the rating is too thin to trust.
MIN_SKILLS_FOR_RATING = 3
CONFIDENT_SKILL_COUNT = 6

_EARLIEST_PLAUSIBLE_YEAR = 1980
# Characters that mark a skill as part of a list rather than a sentence.
_LIST_NEIGHBOURS = set(",/|;•·-–—()[]:\n\t")
# How far away another skill can be and still disambiguate this one.
_CONTEXT_WINDOW = 40

_REQUIREMENT_CUES = re.compile(
    r"(requir|must have|you have|you'll have|looking for"
    r"|expect|essential|qualificat|\d\+?\s*years)",
    re.IGNORECASE,
)
_YEARS_NEAR_EXPERIENCE = re.compile(
    r"(\d{1,2})\s*\+?\s*(?:or more\s*)?years?[^.\n]{0,40}?experience", re.IGNORECASE
)
_EXPERIENCE_NEAR_YEARS = re.compile(
    r"experience[^.\n]{0,40}?(\d{1,2})\s*\+?\s*years?", re.IGNORECASE
)
_YEAR_TOKEN = re.compile(r"\b(19[89]\d|20[0-4]\d)\b")


def _build_alias_pattern() -> tuple[re.Pattern[str], dict[str, str]]:
    """One alternation over every alias, longest first so `node.js` beats `node`."""
    alias_to_skill: dict[str, str] = {}
    for skill, aliases in SKILLS.items():
        for alias in aliases:
            alias_to_skill[alias] = skill

    ordered = sorted(alias_to_skill, key=len, reverse=True)
    # Guards instead of \b: aliases end in +, # or . where \b does the wrong thing.
    pattern = (
        r"(?<![A-Za-z0-9_+#])(" + "|".join(re.escape(a) for a in ordered) + r")(?![A-Za-z0-9_+#])"
    )
    return re.compile(pattern, re.IGNORECASE), alias_to_skill


_ALIAS_RE, _ALIAS_TO_SKILL = _build_alias_pattern()


@dataclass(slots=True)
class SkillHit:
    skill: str
    weight: int = WEIGHT_MENTIONED
    # Where it was found, for the "why this score" breakdown.
    source: str = "mentioned"


@dataclass(slots=True)
class MatchResult:
    score: int | None
    rating: str
    confidence: str
    matched: list[SkillHit] = field(default_factory=list)
    missing: list[SkillHit] = field(default_factory=list)
    extra: list[str] = field(default_factory=list)
    coverage: float | None = None
    required_years: int | None = None
    resume_years: int | None = None
    years_basis: str | None = None
    explanation: str = ""


def find_skills(text: str | None) -> dict[str, list[tuple[int, int]]]:
    """Canonical skill -> the spans where it was found.

    Ambiguous aliases (`go`, `c`, `r`, ...) only count when they read as part of
    a list or sit near another skill, so prose like "go to the office" is not a
    hit for Go.
    """
    if not text:
        return {}

    raw: list[tuple[str, int, int, bool]] = []
    for match in _ALIAS_RE.finditer(text):
        alias = match.group(1).lower()
        skill = _ALIAS_TO_SKILL[alias]
        raw.append((skill, match.start(), match.end(), alias in AMBIGUOUS_ALIASES))

    unambiguous_positions = [start for _, start, _, ambiguous in raw if not ambiguous]

    found: dict[str, list[tuple[int, int]]] = {}
    for skill, start, end, ambiguous in raw:
        if ambiguous and not _reads_as_a_skill(text, start, end, unambiguous_positions):
            continue
        found.setdefault(skill, []).append((start, end))
    return found


def _reads_as_a_skill(text: str, start: int, end: int, other_positions: list[int]) -> bool:
    """True when an ambiguous token looks like a listed technology, not a word."""
    if any(abs(pos - start) <= _CONTEXT_WINDOW and pos != start for pos in other_positions):
        return True

    before = text[:start].rstrip(" \t")
    after = text[end:].lstrip(" \t")
    starts_item = not before or before[-1] in _LIST_NEIGHBOURS
    ends_item = not after or after[0] in _LIST_NEIGHBOURS
    return starts_item and ends_item


def _weigh_posting_skills(raw_text: str | None, extracted: dict | None) -> dict[str, SkillHit]:
    """Collect the posting's skills, weighted by how firmly the posting asks for them.

    Results are cached on the text itself, so rating a page of applications does
    not rescan the same posting on every request and there is nothing to
    invalidate -- different text is simply a different key.
    """
    extracted_key = json.dumps(extracted, sort_keys=True) if extracted else None
    return {hit.skill: hit for hit in _weigh_cached(raw_text, extracted_key)}


@lru_cache(maxsize=256)
def _weigh_cached(raw_text: str | None, extracted_key: str | None) -> tuple[SkillHit, ...]:
    extracted = json.loads(extracted_key) if extracted_key else None
    hits: dict[str, SkillHit] = {}

    def add(skill: str, weight: int, source: str) -> None:  # noqa: D401
        current = hits.get(skill)
        if current is None or weight > current.weight:
            hits[skill] = SkillHit(skill=skill, weight=weight, source=source)

    # Structured extraction, when Claude has run, gives the cleanest weighting.
    for section, weight, source in (
        ("requirements", WEIGHT_REQUIRED, "required"),
        ("tech_stack", WEIGHT_STACK, "tech stack"),
        ("responsibilities", WEIGHT_STACK, "responsibilities"),
        ("nice_to_have", WEIGHT_NICE_TO_HAVE, "nice to have"),
    ):
        for line in (extracted or {}).get(section) or []:
            for skill in find_skills(str(line)):
                add(skill, weight, source)

    # Raw text always contributes; a line that reads like a requirement counts double.
    if raw_text:
        for line in raw_text.splitlines():
            weight, source = (
                (WEIGHT_STACK, "likely required")
                if _REQUIREMENT_CUES.search(line)
                else (WEIGHT_MENTIONED, "mentioned")
            )
            for skill in find_skills(line):
                add(skill, weight, source)

    # A tuple, so a caller can never mutate what the cache holds.
    return tuple(hits.values())


def _stated_years(text: str | None) -> int | None:
    """Largest 'N years of experience' style figure in the text."""
    if not text:
        return None
    values = [
        int(m.group(1))
        for pattern in (_YEARS_NEAR_EXPERIENCE, _EXPERIENCE_NEAR_YEARS)
        for m in pattern.finditer(text)
    ]
    plausible = [v for v in values if 0 < v <= 50]
    return max(plausible) if plausible else None


def _resume_years(text: str | None) -> tuple[int | None, str | None]:
    """Years of experience, and how it was worked out."""
    stated = _stated_years(text)
    if stated is not None:
        return stated, "stated on the resume"

    if not text:
        return None, None

    # Fall back to the span since the earliest year the resume mentions. This is
    # a weaker signal -- a graduation date inflates it -- so it is labelled.
    years = [int(y) for y in _YEAR_TOKEN.findall(text)]
    this_year = date.today().year
    plausible = [y for y in years if _EARLIEST_PLAUSIBLE_YEAR <= y <= this_year]
    if not plausible:
        return None, None
    span = this_year - min(plausible)
    return (span, "inferred from dates on the resume") if 0 < span <= 50 else (None, None)


def rate_match(
    *,
    posting_raw_text: str | None,
    posting_extracted: dict | None,
    resume_text: str | None,
) -> MatchResult:
    """Score how well a resume covers what a posting asks for, 0-100."""
    if not resume_text:
        return MatchResult(
            score=None,
            rating="No resume",
            confidence="none",
            explanation="Upload a resume to get a match rating.",
        )

    posting_skills = _weigh_posting_skills(posting_raw_text, posting_extracted)
    if len(posting_skills) < MIN_SKILLS_FOR_RATING:
        return MatchResult(
            score=None,
            rating="Not enough detail",
            confidence="none",
            explanation=(
                "The posting does not name enough recognisable skills to rate. "
                "Paste the full description, or run extraction on it."
            ),
        )

    resume_skills = _skills_in(resume_text)

    matched = [hit for skill, hit in posting_skills.items() if skill in resume_skills]
    missing = [hit for skill, hit in posting_skills.items() if skill not in resume_skills]
    matched.sort(key=lambda h: (-h.weight, h.skill))
    missing.sort(key=lambda h: (-h.weight, h.skill))

    total_weight = sum(hit.weight for hit in posting_skills.values())
    coverage = sum(hit.weight for hit in matched) / total_weight

    required_years = _stated_years(posting_raw_text)
    resume_years, years_basis = _resume_years(resume_text)

    if required_years and resume_years:
        experience_factor = min(resume_years / required_years, 1.0)
        raw_score = COVERAGE_SHARE * coverage + EXPERIENCE_SHARE * experience_factor
    else:
        # Don't penalise for a signal the documents simply don't carry.
        raw_score = coverage

    score = round(raw_score * 100)
    confidence = "high" if len(posting_skills) >= CONFIDENT_SKILL_COUNT else "medium"

    return MatchResult(
        score=score,
        rating=_rating_label(score),
        confidence=confidence,
        matched=matched,
        missing=missing,
        extra=sorted(resume_skills - set(posting_skills))[:12],
        coverage=round(coverage, 3),
        required_years=required_years,
        resume_years=resume_years,
        years_basis=years_basis,
        explanation=_explain(matched, missing, required_years, resume_years),
    )


@lru_cache(maxsize=64)
def _skills_in(text: str) -> frozenset[str]:
    """Whole-document skill set. Cached: one resume is scanned against many rows."""
    return frozenset(find_skills(text))


def _rating_label(score: int) -> str:
    if score >= 80:
        return "Strong"
    if score >= 60:
        return "Good"
    if score >= 40:
        return "Partial"
    return "Weak"


def _explain(
    matched: list[SkillHit],
    missing: list[SkillHit],
    required_years: int | None,
    resume_years: int | None,
) -> str:
    total = len(matched) + len(missing)
    parts = [f"Your resume covers {len(matched)} of {total} skills the posting names."]

    blocking = [hit.skill for hit in missing if hit.weight >= WEIGHT_STACK]
    if blocking:
        shown = ", ".join(blocking[:4])
        more = f" (+{len(blocking) - 4} more)" if len(blocking) > 4 else ""
        parts.append(f"Not evidenced: {shown}{more}.")

    if required_years and resume_years and resume_years < required_years:
        parts.append(f"Asks for {required_years} years; your resume shows about {resume_years}.")

    return " ".join(parts)
