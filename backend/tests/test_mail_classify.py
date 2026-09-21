"""Tests for reading job mail without a model call.

Two failure modes matter here and they are not symmetric. Missing an update
costs a manual status change; filing a rejection against the wrong company
corrupts the pipeline and is hard to notice. So the matching tests lean on what
should *not* match, and the phrase tests lean on the polite wordings that read
as encouraging and are not.
"""

import uuid

import pytest

from app.mail.classify import (
    ApplicationTarget,
    classify,
    guard_transition,
    is_worth_reading,
    shortlist,
)
from app.mail.provider import MessageBody, MessageHeader
from app.models import ApplicationStatus

ACME = ApplicationTarget(
    application_id=uuid.uuid4(),
    status=ApplicationStatus.applied,
    company_name="Acme Robotics, Inc.",
    company_domain="acmerobotics.com",
    posting_domain="job-boards.greenhouse.io",
    title="Senior Backend Engineer",
)
GLOBEX = ApplicationTarget(
    application_id=uuid.uuid4(),
    status=ApplicationStatus.screening,
    company_name="Globex Corporation",
    company_domain="globex.com",
    title="Staff Platform Engineer",
)
TARGETS = [ACME, GLOBEX]


def header(**kwargs) -> MessageHeader:
    base = {
        "provider_message_id": "m1",
        "from_email": "recruiting@acmerobotics.com",
        "from_name": "Acme Robotics Recruiting",
        "subject": "Your application",
    }
    return MessageHeader(**{**base, **kwargs})


def body(text: str) -> MessageBody:
    return MessageBody(snippet=text[:100], body_text=text)


# ------------------------------------------------------------------ stage one gate


def test_mail_from_the_company_is_worth_reading():
    assert is_worth_reading(header(), TARGETS)


def test_ats_mail_is_worth_reading_even_without_a_company_name():
    assert is_worth_reading(
        header(from_email="no-reply@greenhouse.io", from_name="Greenhouse", subject="Update"),
        TARGETS,
    )


def test_unrelated_mail_is_skipped():
    assert not is_worth_reading(
        header(
            from_email="newsletter@some-blog.com",
            from_name="Some Blog",
            subject="This week in tech",
        ),
        TARGETS,
    )


def test_job_board_digests_are_skipped():
    """A LinkedIn alert names companies we do not track; it is not an update."""
    assert not is_worth_reading(
        header(
            from_email="jobs-listings@linkedin.com",
            from_name="LinkedIn Job Alerts",
            subject="30 new jobs for you",
            list_id="<jobs.linkedin.com>",
        ),
        TARGETS,
    )


def test_a_thread_we_already_filed_is_always_worth_reading():
    """Later replies rarely name the company again."""
    bare = header(from_email="sarah@gmail.com", from_name="Sarah", subject="Re: chat")
    assert not is_worth_reading(bare, TARGETS)
    assert is_worth_reading(bare, TARGETS, thread_application=ACME.application_id)


# -------------------------------------------------------------------- status reading


@pytest.mark.parametrize(
    "text",
    [
        "Thank you for interviewing with us. Unfortunately, we have decided to move "
        "forward with other candidates.",
        "We regret to inform you that we will not be moving forward with your application.",
        "After careful review, we've decided not to proceed with your candidacy.",
        "We won't be able to extend an offer at this time.",
    ],
)
def test_rejections_read_as_rejections(text):
    verdict = classify(header(), body(text), TARGETS)
    assert verdict is not None
    assert verdict.suggested_status == ApplicationStatus.rejected


def test_a_rejection_that_mentions_interviews_is_still_a_rejection():
    """The warm wrapper is the norm, not the exception."""
    text = (
        "Thank you so much for taking the time to interview with our team — we were "
        "impressed by your background. Unfortunately, we have decided to move forward "
        "with other candidates for this role."
    )
    verdict = classify(header(), body(text), TARGETS)
    assert verdict.suggested_status == ApplicationStatus.rejected


def test_interview_invitation_reads_as_interviewing():
    text = "We'd like to invite you to an onsite interview with the platform team."
    verdict = classify(header(), body(text), TARGETS)
    assert verdict.suggested_status == ApplicationStatus.interviewing


def test_recruiter_screen_reads_as_screening():
    text = "I'd love to set up a time to chat about your application — a quick 30 minute call."
    verdict = classify(header(), body(text), TARGETS)
    assert verdict.suggested_status == ApplicationStatus.screening


def test_offer_reads_as_offer():
    text = "We are delighted to offer you the position of Senior Backend Engineer."
    verdict = classify(header(), body(text), TARGETS)
    assert verdict.suggested_status == ApplicationStatus.offer


def test_an_acknowledgement_for_an_already_applied_role_proposes_nothing():
    """`applied` is where it already is, so there is nothing to suggest."""
    text = "We have received your application and will be in touch."
    verdict = classify(header(), body(text), TARGETS)
    assert verdict is not None
    assert verdict.application_id == ACME.application_id
    assert verdict.suggested_status is None


def test_mail_with_no_status_language_still_links_to_the_application():
    text = "Attaching the parking information for the office. Let me know if you need anything."
    verdict = classify(header(), body(text), TARGETS)
    assert verdict is not None
    assert verdict.suggested_status is None
    assert verdict.confidence < 1.0


# ------------------------------------------------------------------------- matching


def test_sender_domain_picks_the_right_application():
    verdict = classify(
        header(from_email="people@globex.com", from_name="Globex People"),
        body("We'd like to invite you to a technical interview."),
        TARGETS,
    )
    assert verdict.application_id == GLOBEX.application_id


def test_an_unmatched_email_is_dropped():
    verdict = classify(
        header(from_email="hr@initech.com", from_name="Initech", subject="An opportunity"),
        body("We have a role that might interest you."),
        TARGETS,
    )
    assert verdict is None


def test_two_roles_at_one_company_are_not_guessed_between():
    """A coin flip between two applications is worse than no suggestion."""
    other_role = ApplicationTarget(
        application_id=uuid.uuid4(),
        status=ApplicationStatus.applied,
        company_name="Acme Robotics, Inc.",
        company_domain="acmerobotics.com",
        title="Senior Frontend Engineer",
    )
    verdict = classify(
        header(subject="An update on your application"),
        body("Unfortunately we are moving forward with other candidates."),
        [ACME, other_role],
    )
    assert verdict is None


def test_the_role_title_disambiguates_two_roles_at_one_company():
    other_role = ApplicationTarget(
        application_id=uuid.uuid4(),
        status=ApplicationStatus.applied,
        company_name="Acme Robotics, Inc.",
        company_domain="acmerobotics.com",
        title="Senior Frontend Engineer",
    )
    verdict = classify(
        header(subject="Your Senior Backend Engineer application"),
        body("Unfortunately we are moving forward with other candidates."),
        [ACME, other_role],
    )
    assert verdict.application_id == ACME.application_id


def test_thread_continuity_beats_an_absent_company_name():
    verdict = classify(
        header(from_email="sarah@gmail.com", from_name="Sarah", subject="Re: next steps"),
        body("Can you do Thursday for the technical interview?"),
        TARGETS,
        thread_application=GLOBEX.application_id,
    )
    assert verdict.application_id == GLOBEX.application_id
    assert verdict.suggested_status == ApplicationStatus.interviewing


def test_a_bounce_subdomain_still_reads_as_the_company():
    verdict = classify(
        header(from_email="noreply@careers.mail.acmerobotics.com", from_name="Careers"),
        body("We are delighted to offer you the role."),
        TARGETS,
    )
    assert verdict.application_id == ACME.application_id


# --------------------------------------------------------------------- transitions


def test_a_suggestion_never_moves_an_application_backwards():
    """An autoresponder landing after a phone screen does not un-screen you."""
    assert guard_transition(ApplicationStatus.interviewing, ApplicationStatus.applied) is None


def test_a_suggestion_matching_the_current_status_is_dropped():
    assert guard_transition(ApplicationStatus.screening, ApplicationStatus.screening) is None


def test_a_closed_application_is_not_reopened():
    assert guard_transition(ApplicationStatus.rejected, ApplicationStatus.interviewing) is None


def test_a_closed_application_can_change_how_it_closed():
    assert (
        guard_transition(ApplicationStatus.withdrawn, ApplicationStatus.rejected)
        == ApplicationStatus.rejected
    )


def test_forward_moves_pass():
    assert (
        guard_transition(ApplicationStatus.applied, ApplicationStatus.interviewing)
        == ApplicationStatus.interviewing
    )


# ---------------------------------------------------------------------- shortlisting


def test_the_shortlist_ranks_plausible_applications_first():
    candidates = shortlist(header(), body("An update on your application."), TARGETS)
    assert candidates[0] is ACME


def test_the_shortlist_falls_back_to_open_applications():
    """An unrecognised ATS domain still deserves a shortlist to reason about."""
    closed = ApplicationTarget(
        application_id=uuid.uuid4(),
        status=ApplicationStatus.rejected,
        company_name="Initech",
    )
    candidates = shortlist(
        header(from_email="noreply@unknown-ats.example", from_name="Careers", subject="Update"),
        body("An update."),
        [*TARGETS, closed],
    )
    assert closed not in candidates
    assert sorted(t.company_name for t in candidates) == [
        "Acme Robotics, Inc.",
        "Globex Corporation",
    ]
