"""Tests for the experience record: its text rendering and resume layout.

These are the two places the record turns into something else -- the text the
matcher and the model read, and the blocks a resume is rendered from -- so they
are where a mistake would silently change every score and every document.
"""

from dataclasses import dataclass, field
from datetime import date

from app.experience import experience_text, format_period, is_empty
from app.render import resume_blocks


# Light stand-ins for the ORM objects: these functions only read attributes,
# and a real session would make the tests slower without testing more.
@dataclass
class FakeHighlight:
    text: str


@dataclass
class FakeRole:
    company: str
    title: str
    start_date: date | None = None
    end_date: date | None = None
    location: str | None = None
    summary: str | None = None
    highlights: list = field(default_factory=list)


@dataclass
class FakeStory:
    title: str
    body: str
    skills: list = field(default_factory=list)


@dataclass
class FakeEducation:
    institution: str
    credential: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    notes: str | None = None


@dataclass
class FakeProfile:
    full_name: str | None = "Alex Milligan"
    headline: str | None = "Staff Platform Engineer"
    email: str | None = "alex@example.com"
    phone: str | None = None
    location: str | None = "Remote (EU)"
    links: list = field(default_factory=list)
    summary: str | None = "Platform engineer with 12 years of experience."
    skills: list = field(default_factory=lambda: ["Python", "Kubernetes"])
    roles: list = field(default_factory=list)
    stories: list = field(default_factory=list)
    education: list = field(default_factory=list)


def a_profile() -> FakeProfile:
    return FakeProfile(
        roles=[
            FakeRole(
                company="Northwind Labs",
                title="Staff Platform Engineer",
                start_date=date(2021, 3, 1),
                highlights=[FakeHighlight("Ran Kubernetes across three AWS accounts.")],
            )
        ],
        stories=[
            FakeStory(
                title="Migrating billing",
                body="Two weeks of instrumentation before touching any code.",
                skills=["Python"],
            )
        ],
        education=[FakeEducation(institution="TU Berlin", credential="BSc")],
    )


# --------------------------------------------------------------------------- periods


def test_period_with_both_ends():
    assert format_period(date(2017, 1, 1), date(2021, 2, 1)) == "Jan 2017 – Feb 2021"


def test_open_ended_role_reads_as_present():
    assert format_period(date(2021, 3, 1), None) == "Mar 2021 – Present"


def test_missing_start_does_not_render_a_placeholder():
    """A lone '?' looks like a bug on a printed resume."""
    assert format_period(None, date(2014, 6, 1)) == "Jun 2014"
    assert "?" not in format_period(None, date(2014, 6, 1))


def test_no_dates_is_empty():
    assert format_period(None, None) == ""


# ------------------------------------------------------------------------ record text


def test_text_includes_the_whole_record():
    text = experience_text(a_profile())
    assert "Alex Milligan" in text
    assert "Northwind Labs" in text
    assert "Ran Kubernetes across three AWS accounts." in text
    assert "TU Berlin" in text


def test_stories_can_be_excluded_for_the_matcher():
    """The matcher skips stories so their length can't inflate the term count."""
    profile = a_profile()
    with_stories = experience_text(profile, include_stories=True)
    without = experience_text(profile, include_stories=False)

    assert "Migrating billing" in with_stories
    assert "Migrating billing" not in without
    # The role evidence survives either way.
    assert "Ran Kubernetes across three AWS accounts." in without


def test_empty_profile_is_detected():
    assert is_empty(FakeProfile(summary=None, roles=[], stories=[]))
    assert not is_empty(a_profile())


def test_a_summary_alone_counts_as_non_empty():
    assert not is_empty(FakeProfile(roles=[], stories=[], summary="Ten years of backend work."))


# ----------------------------------------------------------------------- resume layout


def a_role_dict(**overrides) -> dict:
    base = {
        "title": "Staff Platform Engineer",
        "company": "Northwind Labs",
        "location": "Remote",
        "period": "Mar 2021 – Present",
        "summary": None,
        "highlights": ["Ran Kubernetes across three AWS accounts."],
    }
    return {**base, **overrides}


def test_sections_render_in_template_order():
    blocks = resume_blocks(
        summary="A summary.",
        skills=["Python"],
        roles=[a_role_dict()],
        education=[{"institution": "TU Berlin", "credential": "BSc", "period": "Jun 2014"}],
        sections=["skills", "summary", "experience", "education"],
    )
    headings = [b.text for b in blocks if b.kind == "heading" and b.level == 2]
    assert headings == ["Skills", "Summary", "Experience", "Education"]


def test_a_section_the_template_omits_is_not_rendered():
    blocks = resume_blocks(
        summary="A summary.",
        skills=["Python"],
        roles=[a_role_dict()],
        education=[],
        sections=["experience"],
    )
    headings = [b.text for b in blocks if b.kind == "heading"]
    assert "Summary" not in headings
    assert "Skills" not in headings


def test_empty_sections_are_skipped_even_when_requested():
    """An empty Education heading with nothing under it looks broken."""
    blocks = resume_blocks(
        summary=None,
        skills=[],
        roles=[a_role_dict()],
        education=[],
        sections=["summary", "skills", "experience", "education"],
    )
    headings = [b.text for b in blocks if b.kind == "heading" and b.level == 2]
    assert headings == ["Experience"]


def test_role_header_carries_company_and_dates():
    blocks = resume_blocks(
        summary=None,
        skills=[],
        roles=[a_role_dict()],
        education=[],
        sections=["experience"],
    )
    role_heading = next(b for b in blocks if b.kind == "heading" and b.level == 3)
    assert "Staff Platform Engineer" in role_heading.text
    assert "Northwind Labs" in role_heading.text
    assert "Mar 2021 – Present" in role_heading.text


def test_roles_sit_below_their_section_heading():
    """Hierarchy matters: a role must not read as prominently as 'Experience'."""
    blocks = resume_blocks(
        summary=None,
        skills=[],
        roles=[a_role_dict()],
        education=[],
        sections=["experience"],
    )
    section = next(b for b in blocks if b.kind == "heading" and b.text == "Experience")
    role = next(b for b in blocks if b.kind == "heading" and b.text != "Experience")
    assert section.level < role.level


def test_highlights_render_as_bullets():
    blocks = resume_blocks(
        summary=None,
        skills=[],
        roles=[a_role_dict(highlights=["First thing.", "Second thing."])],
        education=[],
        sections=["experience"],
    )
    bullets = [b.text for b in blocks if b.kind == "bullet"]
    assert bullets == ["First thing.", "Second thing."]
