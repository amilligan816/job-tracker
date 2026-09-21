"""Tests for resolving a career-page URL to the posting behind it.

The failure these guard against is quiet: a career page that renders its
posting client-side still serves 1-2kB of navigation, EEO text and cookie
notices. That is plenty of text to pass a "did we get anything?" check and
plenty to make an extractor invent a posting from the page furniture, so the
user gets a confident, wrong record instead of an error.
"""

import httpx
import pytest

from app import ats
from app.ats import (
    _ashby_posting,
    _ashby_target,
    _greenhouse_posting,
    _greenhouse_target,
    _lever_posting,
    _lever_target,
    _org_candidates,
    _workday_posting,
    _workday_target,
    resolve_posting,
)
from app.textextract import _render_ats_posting

BILLTRUST_URL = (
    "https://www.billtrust.com/careers/job-openings/careers-job-details-application"
    "?gh_jid=7826842003&source=billtrust&gh_src=null"
)
JOB_UUID = "d3bc1ced-3ce4-4086-a050-555055dbb1ff"
ZILLOW_URL = (
    "https://zillow.wd5.myworkdayjobs.com/Zillow_Group_External/job/Remote-USA"
    "/Software-Development-Engineer_P748929-1?source=LinkedIn"
)

GREENHOUSE_JSON = {
    "title": "Senior Software Engineer",
    "company_name": "Billtrust US Careers",
    "location": {"name": "United States (Remote)"},
    "metadata": [{"name": "Employment Type", "value": "Regular", "value_type": "single_select"}],
    "content": "&lt;p&gt;Build things.&lt;/p&gt;&lt;p&gt;5+ years experience.&lt;/p&gt;",
    "absolute_url": "https://www.billtrust.com/careers/job-openings/?gh_jid=7826842003",
}

LEVER_JSON = {
    "id": JOB_UUID,
    "text": "Customer Success Manager",
    "categories": {
        "location": "Baltimore, MD",
        "team": "Operations",
        "commitment": "Regular Full Time (Salary)",
    },
    "workplaceType": "remote",
    "description": "<div>We help teams hire.</div>",
    "lists": [
        {"text": "Skill Set:", "content": "<li>3+ years of account management</li>"},
        {"text": "Within 1 Month:", "content": "<li>Attend onboarding</li>"},
    ],
    "additional": "<div>We are an equal opportunity employer.</div>",
    "hostedUrl": f"https://jobs.lever.co/leverdemo/{JOB_UUID}",
}

WORKDAY_JSON = {
    "hiringOrganization": {"name": "ZINC Zillow, Inc.", "url": ""},
    "jobPostingInfo": {
        "title": "Software Development Engineer",
        "location": "Remote-USA",
        "timeType": "Full time",
        "remoteType": "Remote",
        "jobReqId": "P748929",
        # Workday double-encodes: `&amp;#xa;` is an escaped newline entity.
        "jobDescription": (
            "<h2>About the team</h2><p>Build things.</p>"
            "&amp;#xa;&amp;#xa;<p>Base pay $136,300.00 - $217,700.00 annually.</p>"
        ),
        "externalUrl": (
            "https://zillow.wd5.myworkdayjobs.com/Zillow_Group_External/job/Remote-USA"
            "/Software-Development-Engineer_P748929-1"
        ),
    },
}

ASHBY_JSON = {
    "id": JOB_UUID,
    "title": "Senior / Staff Fullstack Engineer",
    "location": "Europe",
    "secondaryLocations": [],
    "employmentType": "FullTime",
    "isRemote": True,
    "workplaceType": "Remote",
    "descriptionHtml": "<p>Build the app.</p>",
    "compensation": {
        "scrapeableCompensationSalarySummary": "€110K - €185K",
        "compensationTierSummary": "€110K – €185K • Offers Equity • Offers Bonus",
    },
    "jobUrl": f"https://jobs.ashbyhq.com/linear/{JOB_UUID}",
}


def transport(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def json_route(routes: dict[str, dict]):
    """Serve a payload per URL fragment, 404 for anything unmatched."""

    def handler(request: httpx.Request) -> httpx.Response:
        for fragment, payload in routes.items():
            if fragment in str(request.url):
                return httpx.Response(200, json=payload)
        return httpx.Response(404, json={"error": "Document not found"})

    return handler


# -------------------------------------------------------------------- target parsing


def test_greenhouse_job_id_comes_from_the_gh_jid_parameter():
    endpoints, job_id = _greenhouse_target(BILLTRUST_URL)
    assert job_id == "7826842003"
    assert endpoints[0] == "https://boards-api.greenhouse.io/v1/boards/billtrust/jobs/7826842003"


def test_host_supplies_an_org_guess_when_the_query_string_does_not():
    endpoints, job_id = _greenhouse_target("https://careers.acme.io/openings?gh_jid=42")
    assert job_id == "42"
    assert endpoints == ["https://boards-api.greenhouse.io/v1/boards/acme/jobs/42"]


def test_placeholder_parameter_values_are_not_treated_as_tokens():
    # Billtrust's own links carry `gh_src=null`; "null" is not an org.
    assert "null" not in _org_candidates({"source": ["null"], "for": [""]}, "www.acme.com")


def test_a_direct_greenhouse_url_needs_no_guessing():
    endpoints, job_id = _greenhouse_target("https://job-boards.greenhouse.io/acme/jobs/991")
    assert job_id == "991"
    assert endpoints == ["https://boards-api.greenhouse.io/v1/boards/acme/jobs/991"]


def test_lever_reads_the_site_and_uuid_out_of_the_path():
    endpoints, job_id = _lever_target(f"https://jobs.lever.co/leverdemo/{JOB_UUID}")
    assert job_id == JOB_UUID
    assert endpoints == [f"https://api.lever.co/v0/postings/leverdemo/{JOB_UUID}"]


def test_lever_tolerates_the_apply_suffix():
    endpoints, job_id = _lever_target(f"https://jobs.lever.co/leverdemo/{JOB_UUID}/apply")
    assert job_id == JOB_UUID
    assert endpoints == [f"https://api.lever.co/v0/postings/leverdemo/{JOB_UUID}"]


def test_ashby_reads_the_org_and_uuid_out_of_the_path():
    endpoints, job_id = _ashby_target(f"https://jobs.ashbyhq.com/linear/{JOB_UUID}/application")
    assert job_id == JOB_UUID
    assert endpoints == [
        "https://api.ashbyhq.com/posting-api/job-board/linear?includeCompensation=true"
    ]


def test_ashby_embedded_on_a_company_page_guesses_the_org_from_the_host():
    endpoints, job_id = _ashby_target(f"https://careers.acme.com/roles?ashby_jid={JOB_UUID}")
    assert job_id == JOB_UUID
    assert endpoints == [
        "https://api.ashbyhq.com/posting-api/job-board/acme?includeCompensation=true"
    ]


# ------------------------------------------------------------------- workday targets


def test_workday_builds_the_cxs_endpoint_from_the_host_and_path():
    endpoints, job_id = _workday_target(ZILLOW_URL)
    assert job_id == "Remote-USA/Software-Development-Engineer_P748929-1"
    # Tenant from the first host label, site from the segment before `job`, and
    # no trailing slash -- Workday answers 406 to one.
    assert endpoints == [
        "https://zillow.wd5.myworkdayjobs.com/wday/cxs/zillow/Zillow_Group_External"
        "/job/Remote-USA/Software-Development-Engineer_P748929-1"
    ]


def test_workday_skips_an_optional_locale_segment():
    endpoints, _ = _workday_target(
        "https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/job/US-CA/Eng_JR1"
    )
    assert endpoints == [
        "https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/NVIDIAExternalCareerSite"
        "/job/US-CA/Eng_JR1"
    ]


@pytest.mark.parametrize(
    "url",
    [
        "https://zillow.wd5.myworkdayjobs.com/Zillow_Group_External",  # board index
        "https://zillow.wd5.myworkdayjobs.com/job/Remote-USA",  # no site segment
        "https://zillow.wd5.myworkdayjobs.com/Site/job",  # no job path
    ],
)
def test_a_workday_url_that_is_not_a_posting_is_declined(url):
    assert _workday_target(url) == ([], None)


@pytest.mark.parametrize(
    "url",
    [
        "https://acme.com/careers/senior-engineer",
        "https://jobs.lever.co/leverdemo",  # a board index, not a posting
        "https://jobs.lever.co/leverdemo/not-a-uuid",
        "https://jobs.ashbyhq.com/linear",
    ],
)
def test_a_url_with_no_resolvable_job_is_not_ours(url):
    # `resolve_posting` needs both an org to ask and a job to ask about.
    resolvable = [
        target.__name__
        for target in (_greenhouse_target, _lever_target, _ashby_target)
        if all(target(url))
    ]
    assert resolvable == []


async def test_a_non_ats_url_resolves_to_none_so_the_caller_scrapes():
    assert await resolve_posting("https://acme.com/careers/senior-engineer") is None


# ------------------------------------------------------------------- greenhouse fetch


async def test_a_wrong_org_guess_falls_through_to_the_right_one():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if "/boards/wrongguess/" in str(request.url):
            return httpx.Response(404, json={"error": "Not found"})
        return httpx.Response(200, json=GREENHOUSE_JSON)

    async with transport(handler) as client:
        posting = await resolve_posting(
            "https://www.acme.com/careers?gh_jid=7826842003&source=wrongguess", client
        )

    assert posting is not None and posting.title == "Senior Software Engineer"
    assert len(seen) == 2, "should have tried the query-string token before the host"


async def test_no_org_guess_matching_gives_up_rather_than_raising():
    async with transport(lambda _: httpx.Response(404, json={})) as client:
        assert await resolve_posting(BILLTRUST_URL, client) is None


async def test_a_transport_error_gives_up_rather_than_raising():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    async with transport(handler) as client:
        assert await resolve_posting(BILLTRUST_URL, client) is None


async def test_a_non_json_body_gives_up_rather_than_raising():
    async with transport(lambda _: httpx.Response(200, text="<html>nope</html>")) as client:
        assert await resolve_posting(BILLTRUST_URL, client) is None


@pytest.mark.parametrize("payload", [{"title": "Engineer"}, {"content": "&lt;p&gt;x&lt;/p&gt;"}])
def test_a_greenhouse_payload_missing_title_or_content_is_not_a_posting(payload):
    assert _greenhouse_posting(payload) is None


def test_greenhouse_employment_type_is_read_out_of_the_metadata_list():
    posting = _greenhouse_posting(GREENHOUSE_JSON)
    assert posting.employment_type == "Regular"
    assert posting.location == "United States (Remote)"


def test_a_greenhouse_posting_without_that_metadata_key_still_parses():
    assert _greenhouse_posting({**GREENHOUSE_JSON, "metadata": []}).employment_type is None


# ------------------------------------------------------------------------ lever fetch


async def test_lever_resolves_a_posting_from_its_hosted_url():
    async with transport(json_route({"api.lever.co": LEVER_JSON})) as client:
        posting = await resolve_posting(f"https://jobs.lever.co/leverdemo/{JOB_UUID}", client)

    assert posting is not None
    assert posting.ats == "lever"
    assert posting.title == "Customer Success Manager"
    assert posting.location == "Baltimore, MD"
    assert posting.employment_type == "Regular Full Time (Salary)"
    assert posting.workplace == "remote"


def test_lever_body_includes_the_titled_lists_not_just_the_description():
    # The lists hold the requirements; a body built from `description` alone
    # would drop everything that makes the posting matchable.
    text = _render_ats_posting(_lever_posting(LEVER_JSON))
    assert "We help teams hire." in text
    assert "Skill Set:" in text
    assert "3+ years of account management" in text
    assert "equal opportunity" in text


def test_lever_unspecified_workplace_is_dropped_rather_than_reported():
    assert _lever_posting({**LEVER_JSON, "workplaceType": "unspecified"}).workplace is None


def test_a_lever_payload_with_no_title_is_not_a_posting():
    assert _lever_posting({**LEVER_JSON, "text": ""}) is None


def test_a_lever_payload_with_no_body_at_all_is_not_a_posting():
    assert _lever_posting({"text": "Engineer", "description": "", "lists": []}) is None


# ------------------------------------------------------------------------ ashby fetch


async def test_ashby_picks_the_requested_job_out_of_the_whole_board():
    board = {"jobs": [{**ASHBY_JSON, "id": "other-id", "title": "Wrong Job"}, ASHBY_JSON]}
    async with transport(json_route({"ashbyhq.com": board})) as client:
        posting = await resolve_posting(f"https://jobs.ashbyhq.com/linear/{JOB_UUID}", client)

    assert posting is not None
    assert posting.title == "Senior / Staff Fullstack Engineer"
    assert posting.ats == "ashby"
    # The bare range parses better than the tier summary's equity/bonus notes.
    assert posting.compensation == "€110K - €185K"


async def test_a_board_that_does_not_list_the_job_resolves_to_none():
    board = {"jobs": [{**ASHBY_JSON, "id": "someone-else"}]}
    async with transport(json_route({"ashbyhq.com": board})) as client:
        assert await resolve_posting(f"https://jobs.ashbyhq.com/linear/{JOB_UUID}", client) is None


async def test_an_oversized_board_is_abandoned_rather_than_buffered(monkeypatch):
    # A board big enough to matter belongs to an employer with thousands of
    # openings; we would rather lose the posting than buffer the heap.
    monkeypatch.setattr(ats, "_MAX_JSON_BYTES", 10)
    async with transport(json_route({"ashbyhq.com": {"jobs": [ASHBY_JSON]}})) as client:
        assert await resolve_posting(f"https://jobs.ashbyhq.com/linear/{JOB_UUID}", client) is None


def test_ashby_falls_back_to_the_tier_summary_when_there_is_no_bare_range():
    posting = _ashby_posting(
        {**ASHBY_JSON, "compensation": {"compensationTierSummary": "$55K – $80K • Offers Equity"}}
    )
    assert posting.compensation == "$55K – $80K • Offers Equity"


def test_ashby_reports_remote_even_when_workplace_type_is_absent():
    posting = _ashby_posting({**ASHBY_JSON, "workplaceType": None, "isRemote": True})
    assert posting.workplace == "Remote"


def test_ashby_joins_secondary_locations_into_one_line():
    posting = _ashby_posting({**ASHBY_JSON, "secondaryLocations": [{"location": "Remote - US"}]})
    assert posting.location == "Europe, Remote - US"


def test_an_ashby_job_with_no_description_is_not_a_posting():
    assert _ashby_posting({**ASHBY_JSON, "descriptionHtml": ""}) is None


# ---------------------------------------------------------------------- workday fetch


async def test_workday_resolves_a_posting_through_the_cxs_endpoint():
    async with transport(json_route({"/wday/cxs/": WORKDAY_JSON})) as client:
        posting = await resolve_posting(ZILLOW_URL, client)

    assert posting is not None
    assert posting.ats == "workday"
    assert posting.title == "Software Development Engineer"
    assert posting.location == "Remote-USA"
    assert posting.employment_type == "Full time"
    assert posting.workplace == "Remote"


def test_workday_keeps_the_payroll_entity_out_of_the_company_field():
    # "ZINC Zillow, Inc." is an internal entity, not a name to file a company
    # under -- report it as context and let the description supply the real one.
    posting = _workday_posting(WORKDAY_JSON)
    assert posting.company is None
    assert posting.hiring_entity == "ZINC Zillow, Inc."


def test_workday_double_encoded_entities_do_not_survive_into_the_text():
    text = _render_ats_posting(_workday_posting(WORKDAY_JSON))
    assert "&#xa;" not in text
    assert "&amp;" not in text
    assert "Hiring entity: ZINC Zillow, Inc." in text
    assert "Base pay $136,300.00 - $217,700.00 annually." in text


@pytest.mark.parametrize(
    "info",
    [{"title": "Engineer", "jobDescription": ""}, {"title": "", "jobDescription": "<p>x</p>"}],
)
def test_a_workday_payload_missing_title_or_description_is_not_a_posting(info):
    assert _workday_posting({"jobPostingInfo": info}) is None


def test_a_workday_payload_with_no_posting_info_is_declined():
    assert _workday_posting({"hiringOrganization": {"name": "Acme"}}) is None


# ------------------------------------------------------------------------ rendering


def test_rendering_unescapes_the_html_and_keeps_the_header_fields():
    text = _render_ats_posting(_greenhouse_posting(GREENHOUSE_JSON))
    assert text.startswith("Senior Software Engineer")
    assert "Company: Billtrust US Careers" in text
    assert "Employment type: Regular" in text
    # The description arrives as escaped HTML; neither layer may survive.
    assert "Build things." in text
    assert "&lt;" not in text and "<p>" not in text


def test_rendering_reports_workplace_and_compensation_when_the_ats_supplies_them():
    text = _render_ats_posting(_ashby_posting(ASHBY_JSON))
    assert "Workplace: Remote" in text
    assert "Compensation: €110K - €185K" in text
    assert "Build the app." in text


def test_absent_header_fields_are_left_out_rather_than_written_as_none():
    bare = _greenhouse_posting(
        {**GREENHOUSE_JSON, "company_name": None, "location": {}, "metadata": []}
    )
    text = _render_ats_posting(bare)
    assert "None" not in text
    assert "Company:" not in text
