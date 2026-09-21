"""Tests for resolving a career-page URL to the posting behind it.

The failure these guard against is quiet: a career page that renders its
posting client-side still serves 1-2kB of navigation, EEO text and cookie
notices. That is plenty of text to pass a "did we get anything?" check and
plenty to make an extractor invent a posting from the page furniture, so the
user gets a confident, wrong record instead of an error.
"""

import httpx
import pytest

from app.ats import _board_candidates, _greenhouse_posting, _greenhouse_target, resolve_posting
from app.textextract import _render_ats_posting

BILLTRUST_URL = (
    "https://www.billtrust.com/careers/job-openings/careers-job-details-application"
    "?gh_jid=7826842003&source=billtrust&gh_src=null"
)

JOB_JSON = {
    "title": "Senior Software Engineer",
    "company_name": "Billtrust US Careers",
    "location": {"name": "United States (Remote)"},
    "metadata": [{"name": "Employment Type", "value": "Regular", "value_type": "single_select"}],
    "content": "&lt;p&gt;Build things.&lt;/p&gt;&lt;p&gt;5+ years experience.&lt;/p&gt;",
    "absolute_url": "https://www.billtrust.com/careers/job-openings/?gh_jid=7826842003",
}


def transport(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# -------------------------------------------------------------------- target parsing


def test_job_id_comes_from_the_gh_jid_parameter():
    boards, job_id = _greenhouse_target(BILLTRUST_URL)
    assert job_id == "7826842003"
    assert boards[0] == "billtrust"


def test_host_supplies_a_board_guess_when_the_query_string_does_not():
    boards, job_id = _greenhouse_target("https://careers.acme.io/openings?gh_jid=42")
    assert job_id == "42"
    assert boards == ["acme"]


def test_placeholder_parameter_values_are_not_treated_as_tokens():
    # Billtrust's own links carry `gh_src=null`; "null" is not a board.
    assert "null" not in _board_candidates({"source": ["null"], "for": [""]}, "www.acme.com")


def test_a_direct_greenhouse_url_needs_no_guessing():
    boards, job_id = _greenhouse_target("https://job-boards.greenhouse.io/acme/jobs/991")
    assert (boards, job_id) == (["acme"], "991")


def test_a_url_with_no_job_id_is_not_ours():
    assert _greenhouse_target("https://acme.com/careers/senior-engineer") == ([], None)


async def test_a_non_ats_url_resolves_to_none_so_the_caller_scrapes():
    resolved = await resolve_posting("https://acme.com/careers/senior-engineer")
    assert resolved is None


# ------------------------------------------------------------------------- fetching


async def test_a_wrong_board_guess_falls_through_to_the_right_one():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if "/boards/wrongguess/" in request.url.path:
            return httpx.Response(404, json={"error": "Not found"})
        return httpx.Response(200, json=JOB_JSON)

    async with transport(handler) as client:
        posting = await resolve_posting(
            "https://www.acme.com/careers?gh_jid=7826842003&source=wrongguess", client
        )

    assert posting is not None
    assert posting.title == "Senior Software Engineer"
    assert len(seen) == 2, "should have tried the query-string token before the host"


async def test_no_board_guess_matching_gives_up_rather_than_raising():
    async with transport(lambda _: httpx.Response(404, json={})) as client:
        assert await resolve_posting(BILLTRUST_URL, client) is None


async def test_a_transport_error_gives_up_rather_than_raising():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    async with transport(handler) as client:
        assert await resolve_posting(BILLTRUST_URL, client) is None


@pytest.mark.parametrize("payload", [{"title": "Engineer"}, {"content": "&lt;p&gt;x&lt;/p&gt;"}])
def test_a_payload_missing_title_or_content_is_not_a_posting(payload):
    assert _greenhouse_posting(payload) is None


def test_employment_type_is_read_out_of_the_metadata_list():
    posting = _greenhouse_posting(JOB_JSON)
    assert posting.employment_type == "Regular"
    assert posting.location == "United States (Remote)"


def test_a_posting_without_that_metadata_key_still_parses():
    posting = _greenhouse_posting({**JOB_JSON, "metadata": []})
    assert posting.employment_type is None


# ------------------------------------------------------------------------ rendering


def test_rendering_unescapes_the_html_and_keeps_the_header_fields():
    text = _render_ats_posting(_greenhouse_posting(JOB_JSON))
    assert text.startswith("Senior Software Engineer")
    assert "Company: Billtrust US Careers" in text
    assert "Employment type: Regular" in text
    # The description arrives as escaped HTML; neither layer may survive.
    assert "Build things." in text
    assert "&lt;" not in text and "<p>" not in text


def test_absent_header_fields_are_left_out_rather_than_written_as_none():
    bare = _greenhouse_posting({**JOB_JSON, "company_name": None, "location": {}, "metadata": []})
    text = _render_ats_posting(bare)
    assert "None" not in text
    assert "Company:" not in text
