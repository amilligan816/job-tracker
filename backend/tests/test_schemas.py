"""Tests for reading rows that have never had their optional JSONB set.

A brand-new experience profile is the case that matters: the row exists, and
`links` and `skills` are NULL rather than empty, because nothing has written
them yet. Pydantic's `default_factory` does not cover that -- it fills a missing
key, not a present None -- so the read model has to say so explicitly.
"""

import uuid
from datetime import UTC, datetime

from app.schemas import ProfileRead, ResumeTemplateRead, StoryRead


class Row:
    """Stands in for an ORM row, including the attributes left at None."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


NOW = datetime.now(UTC)


def test_a_fresh_profile_reads_without_error():
    """The exact shape `get_or_create_profile` produces on an empty database."""
    profile = ProfileRead.model_validate(
        Row(
            id=uuid.uuid4(),
            full_name=None,
            headline=None,
            email=None,
            phone=None,
            location=None,
            links=None,
            summary=None,
            skills=None,
            roles=[],
            stories=[],
            education=[],
            created_at=NOW,
            updated_at=NOW,
        )
    )
    assert profile.links == []
    assert profile.skills == []


def test_a_populated_profile_keeps_its_values():
    profile = ProfileRead.model_validate(
        Row(
            id=uuid.uuid4(),
            full_name="Alex",
            headline=None,
            email=None,
            phone=None,
            location=None,
            links=[{"label": "GitHub", "url": "https://github.com/alex"}],
            summary=None,
            skills=["Python", "Postgres"],
            roles=[],
            stories=[],
            education=[],
            created_at=NOW,
            updated_at=NOW,
        )
    )
    assert [link.label for link in profile.links] == ["GitHub"]
    assert profile.skills == ["Python", "Postgres"]


def test_a_story_with_no_skills_reads_as_an_empty_list():
    story = StoryRead.model_validate(
        Row(
            id=uuid.uuid4(),
            title="The migration",
            body="We moved 400 tables.",
            role_id=None,
            skills=None,
            source="chat",
            created_at=NOW,
        )
    )
    assert story.skills == []


def test_a_template_with_no_sections_or_options_reads_as_empty():
    template = ResumeTemplateRead.model_validate(
        Row(
            id=uuid.uuid4(),
            name="Bare",
            is_default=False,
            sections=None,
            options=None,
        )
    )
    assert template.sections == []
    assert template.options == {}
