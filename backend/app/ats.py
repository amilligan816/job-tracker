"""Resolve applicant-tracking-system URLs to the posting the browser would show.

Many company career pages are a thin shell around an ATS: the HTML served over
HTTP is navigation, cookie notices and EEO boilerplate, and the posting itself
is fetched by JavaScript after load. Scraping one of those pages is worse than
fetching nothing, because a page of footer text still looks like content -- the
extractor will dutifully assemble a "posting" out of the legal small print.

Where the ATS publishes the same posting over a public JSON API, we ask it
directly instead of scraping the shell. Greenhouse, Lever, Ashby and Workday
all do.
"""

import html
import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

import httpx

logger = logging.getLogger(__name__)

_GREENHOUSE_API = "https://boards-api.greenhouse.io/v1/boards/{org}/jobs/{job_id}"
_LEVER_API = "https://api.lever.co/v0/postings/{org}/{job_id}"
_ASHBY_API = "https://api.ashbyhq.com/posting-api/job-board/{org}?includeCompensation=true"
# Workday's candidate-experience service mirrors the page the browser renders.
_WORKDAY_API = "https://{host}/wday/cxs/{tenant}/{site}/job/{path}"
_WORKDAY_HOSTS = ("myworkdayjobs.com", "myworkdaysite.com")

# An ATS board is addressed by a short token ("billtrust"), which an embedding
# page does not have to state anywhere machine-readable -- Billtrust, for one,
# passes it in `source` and reads it back in its own inline script. So we
# collect plausible tokens and let the API adjudicate: a wrong guess is a 404,
# and the first usable answer wins.
_MAX_ORG_GUESSES = 4

# Ashby publishes no single-job endpoint -- the public posting API serves the
# whole board, which is already megabytes for a mid-size company. Read it with a
# ceiling so a very large employer cannot make us buffer the heap.
_MAX_JSON_BYTES = 8 * 1024 * 1024

_USER_AGENT = "job-tracker/0.1 (+personal job search assistant)"

# Subdomains and suffixes that are never the org token.
_GENERIC_LABELS = frozenset(
    {"www", "careers", "career", "jobs", "job", "apply", "hire", "hiring", "work", "talent"}
)
_PUBLIC_SUFFIXES = frozenset(
    {"com", "org", "net", "io", "co", "ai", "dev", "app", "inc", "us", "uk", "eu", "de", "fr"}
)

# boards.greenhouse.io/acme/jobs/123, job-boards.greenhouse.io/acme/jobs/123
_GREENHOUSE_PATH = re.compile(r"^/(?P<org>[A-Za-z0-9_-]+)/jobs/(?P<job_id>\d+)")
# jobs.lever.co/acme/<uuid>, jobs.ashbyhq.com/acme/<uuid> (+ /apply, /application)
_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_ORG_UUID_PATH = re.compile(rf"^/(?P<org>[A-Za-z0-9_.-]+)/(?P<job_id>{_UUID})")


@dataclass(slots=True)
class AtsPosting:
    """A posting fetched from an ATS API, before it is flattened to text."""

    title: str
    company: str | None
    location: str | None
    employment_type: str | None
    content_html: str
    ats: str
    hiring_entity: str | None = None
    workplace: str | None = None
    compensation: str | None = None
    canonical_url: str | None = None


# A target reads a URL and, when it recognises one, returns the API endpoints
# worth trying (most explicit first) plus the job to pick out of the answer.
# Returning endpoints rather than org tokens is what lets Workday take part: its
# endpoint is built from the host, tenant, site and path all at once.
_Target = Callable[[str], tuple[list[str], str | None]]
# Most parsers get a single job back and ignore `job_id`; Ashby returns a whole
# board and needs it to find the row.
_Parse = Callable[[dict, str], AtsPosting | None]


async def resolve_posting(url: str, client: httpx.AsyncClient | None = None) -> AtsPosting | None:
    """Return the posting behind an ATS URL, or None if this is not one we know.

    Never raises for a posting we simply could not resolve -- the caller falls
    back to scraping the page, which is the right answer for a career page that
    really does serve its postings as HTML.
    """
    for target, parse in _RESOLVERS:
        endpoints, job_id = target(url)
        if not job_id or not endpoints:
            continue
        if client is not None:
            return await _fetch(client, endpoints, job_id, parse)
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=15.0,
            headers={"User-Agent": _USER_AGENT},
        ) as owned:
            return await _fetch(owned, endpoints, job_id, parse)
    return None


async def _fetch(
    client: httpx.AsyncClient, endpoints: list[str], job_id: str, parse: _Parse
) -> AtsPosting | None:
    """Try each candidate endpoint until one yields a posting."""
    for endpoint in endpoints:
        data = await _get_json(client, endpoint)
        if not isinstance(data, dict) and not isinstance(data, list):
            continue
        posting = parse(data, job_id)
        if posting is not None:
            return posting
    return None


# ------------------------------------------------------------------------- greenhouse


def _greenhouse_target(url: str) -> tuple[list[str], str | None]:
    """Pull a job id and candidate board tokens out of a Greenhouse-ish URL."""
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    host = (parsed.hostname or "").lower()

    if host.endswith("greenhouse.io"):
        match = _GREENHOUSE_PATH.match(parsed.path)
        if match:
            return _greenhouse_endpoints([match["org"]], match["job_id"])
        # The embed form: /embed/job_app?for=acme&token=123
        job_id = _first(params, "token", "gh_jid")
        return _greenhouse_endpoints(_org_candidates(params, host), job_id)

    return _greenhouse_endpoints(_org_candidates(params, host), _first(params, "gh_jid"))


def _greenhouse_endpoints(orgs: list[str], job_id: str | None) -> tuple[list[str], str | None]:
    if not job_id:
        return [], None
    return [_GREENHOUSE_API.format(org=org, job_id=job_id) for org in orgs], job_id


def _greenhouse_posting(data: dict, job_id: str = "") -> AtsPosting | None:
    title = (data.get("title") or "").strip()
    content = data.get("content") or ""
    if not title or not content:
        return None

    location = data.get("location") or {}
    return AtsPosting(
        title=title,
        company=(data.get("company_name") or None),
        location=(location.get("name") if isinstance(location, dict) else None) or None,
        employment_type=_metadata_value(data.get("metadata"), {"employment type", "job type"}),
        # Greenhouse double-encodes: the description arrives as HTML-escaped
        # HTML. Normalise it here so every adapter hands back real markup.
        content_html=html.unescape(content),
        ats="greenhouse",
        canonical_url=data.get("absolute_url") or None,
    )


def _metadata_value(metadata, names: set[str]) -> str | None:
    """Greenhouse hangs custom fields off a `metadata` list of name/value pairs."""
    if not isinstance(metadata, list):
        return None
    for item in metadata:
        if (
            isinstance(item, dict)
            and str(item.get("name", "")).lower() in names
            and item.get("value")
        ):
            return str(item["value"])
    return None


# ------------------------------------------------------------------------------ lever


def _lever_target(url: str) -> tuple[list[str], str | None]:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if not host.endswith("lever.co"):
        return [], None
    match = _ORG_UUID_PATH.match(parsed.path)
    if not match:
        return [], None
    job_id = match["job_id"]
    return [_LEVER_API.format(org=match["org"], job_id=job_id)], job_id


def _lever_posting(data: dict, job_id: str = "") -> AtsPosting | None:
    title = (data.get("text") or "").strip()
    if not title:
        return None

    categories = data.get("categories") or {}
    if not isinstance(categories, dict):
        categories = {}

    # Lever splits a posting across `description`, a run of titled `lists` and a
    # closing `additional`. The lists hold the requirements and responsibilities,
    # so a body built from `description` alone loses the substance of the posting.
    sections = [data.get("description") or ""]
    for block in data.get("lists") or []:
        if not isinstance(block, dict):
            continue
        heading = (block.get("text") or "").strip()
        content = block.get("content") or ""
        if heading:
            sections.append(f"<h3>{heading}</h3>")
        if content:
            sections.append(f"<ul>{content}</ul>")
    sections.append(data.get("additional") or "")

    content_html = "\n".join(part for part in sections if part.strip())
    if not content_html:
        return None

    workplace = data.get("workplaceType")
    return AtsPosting(
        title=title,
        # Lever's public payload never names the company; the description almost
        # always does, so leave it to the extractor rather than guessing from the
        # URL token.
        company=None,
        location=categories.get("location") or None,
        employment_type=categories.get("commitment") or None,
        content_html=content_html,
        ats="lever",
        workplace=workplace if workplace and workplace != "unspecified" else None,
        canonical_url=data.get("hostedUrl") or None,
    )


# ------------------------------------------------------------------------------ ashby


def _ashby_target(url: str) -> tuple[list[str], str | None]:
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    host = (parsed.hostname or "").lower()

    if host.endswith("ashbyhq.com"):
        match = _ORG_UUID_PATH.match(parsed.path)
        if match:
            return _ashby_endpoints([match["org"]], match["job_id"])
        return _ashby_endpoints(_org_candidates(params, host), _first(params, "ashby_jid"))

    return _ashby_endpoints(_org_candidates(params, host), _first(params, "ashby_jid"))


def _ashby_endpoints(orgs: list[str], job_id: str | None) -> tuple[list[str], str | None]:
    if not job_id:
        return [], None
    return [_ASHBY_API.format(org=org) for org in orgs], job_id


def _ashby_board(board: dict, job_id: str) -> AtsPosting | None:
    """Ashby publishes no per-job endpoint, so pick the job out of the whole board."""
    jobs = board.get("jobs")
    if not isinstance(jobs, list):
        return None
    for job in jobs:
        if isinstance(job, dict) and job.get("id") == job_id:
            return _ashby_posting(job)
    logger.info("Ashby board does not list job %s", job_id)
    return None


def _ashby_posting(job: dict, job_id: str = "") -> AtsPosting | None:
    title = (job.get("title") or "").strip()
    content = job.get("descriptionHtml") or ""
    if not title or not content:
        return None

    compensation = job.get("compensation") or {}
    if not isinstance(compensation, dict):
        compensation = {}
    # `compensationTierSummary` carries the equity/bonus notes too; the
    # scrapeable summary is the bare range and is the better parse target.
    salary = compensation.get("scrapeableCompensationSalarySummary") or compensation.get(
        "compensationTierSummary"
    )

    locations = [job.get("location")] + list(job.get("secondaryLocations") or [])
    names = [item.get("location") if isinstance(item, dict) else item for item in locations if item]
    workplace = job.get("workplaceType")
    if not workplace and job.get("isRemote"):
        workplace = "Remote"

    return AtsPosting(
        title=title,
        # Ashby's board payload has no organisation name either.
        company=None,
        location=", ".join(str(name) for name in names if name) or None,
        employment_type=job.get("employmentType") or None,
        content_html=content,
        ats="ashby",
        workplace=workplace or None,
        compensation=str(salary) if salary else None,
        canonical_url=job.get("jobUrl") or None,
    )


# ---------------------------------------------------------------------------- workday


def _workday_target(url: str) -> tuple[list[str], str | None]:
    """Map a Workday careers URL onto its candidate-experience endpoint.

    A posting lives at `<tenant>.<datacentre>.myworkdayjobs.com/[locale/]<site>/
    job/<location>/<slug>`, and the JSON behind it at `/wday/cxs/<tenant>/<site>/
    job/<location>/<slug>`. The tenant is the first label of the host, and the
    site is whatever segment precedes `job` -- found by position rather than
    index, because the locale segment is optional.
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if not host.endswith(_WORKDAY_HOSTS):
        return [], None

    parts = [part for part in parsed.path.split("/") if part]
    if "job" not in parts:
        return [], None
    marker = parts.index("job")
    if marker == 0 or marker == len(parts) - 1:
        return [], None

    path = "/".join(parts[marker + 1 :])
    endpoint = _WORKDAY_API.format(
        host=host,
        tenant=host.split(".")[0],
        site=parts[marker - 1],
        # Workday answers 406 to a trailing slash, so the path is joined bare.
        path=path,
    )
    return [endpoint], path


def _workday_posting(data: dict, job_id: str = "") -> AtsPosting | None:
    info = data.get("jobPostingInfo")
    if not isinstance(info, dict):
        return None
    title = (info.get("title") or "").strip()
    content = info.get("jobDescription") or ""
    if not title or not content:
        return None

    organization = data.get("hiringOrganization")
    entity = organization.get("name") if isinstance(organization, dict) else None

    return AtsPosting(
        title=title,
        # `hiringOrganization` is the payroll entity -- "ZINC Zillow, Inc.",
        # "2100 NVIDIA USA" -- not a name anyone would file the company under, and
        # not what the extractor should key a Company row on. Pass it as context
        # instead and let the description supply the real name.
        company=None,
        hiring_entity=entity or None,
        location=info.get("location") or None,
        employment_type=info.get("timeType") or None,
        # Workday double-encodes parts of its description, so `&amp;#xa;` would
        # otherwise survive into the text as a literal "&#xa;".
        content_html=html.unescape(content),
        ats="workday",
        workplace=info.get("remoteType") or None,
        canonical_url=info.get("externalUrl") or None,
    )


# ---------------------------------------------------------------------------- shared

_RESOLVERS: tuple[tuple[_Target, _Parse], ...] = (
    (_greenhouse_target, _greenhouse_posting),
    (_lever_target, _lever_posting),
    (_ashby_target, _ashby_board),
    (_workday_target, _workday_posting),
)


async def _get_json(client: httpx.AsyncClient, url: str) -> dict | list | None:
    """GET a JSON document, or None for any reason it could not be read.

    Every failure is the same to the caller -- try the next org guess, then fall
    back to scraping -- so this swallows the difference and logs it.
    """
    try:
        async with client.stream("GET", url) as response:
            if response.status_code == 404:
                return None
            if response.status_code >= 400:
                logger.warning("ATS returned %s for %s", response.status_code, url)
                return None
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body += chunk
                if len(body) > _MAX_JSON_BYTES:
                    logger.warning("ATS response for %s exceeded %d bytes", url, _MAX_JSON_BYTES)
                    return None
        return json.loads(body)
    except httpx.HTTPError:
        logger.warning("ATS lookup failed for %s", url, exc_info=True)
        return None
    except (ValueError, TypeError):
        logger.warning("ATS response for %s was not JSON", url, exc_info=True)
        return None


def _org_candidates(params: dict[str, list[str]], host: str) -> list[str]:
    """Org tokens worth trying, most explicit first."""
    candidates: list[str] = []

    def add(value: str | None) -> None:
        value = (value or "").strip().lower()
        if value and value not in candidates and re.fullmatch(r"[a-z0-9_-]+", value):
            candidates.append(value)

    # An explicit token in the query string beats anything guessed from the host.
    for key in ("for", "board", "gh_board", "source", "company", "org"):
        add(_first(params, key))

    for label in host.split("."):
        if label not in _GENERIC_LABELS and label not in _PUBLIC_SUFFIXES:
            add(label)

    return candidates[:_MAX_ORG_GUESSES]


def _first(params: dict[str, list[str]], *keys: str) -> str | None:
    for key in keys:
        for value in params.get(key, []):
            value = value.strip()
            # Billtrust's own links carry `gh_src=null`; treat that as absent.
            if value and value.lower() not in {"null", "undefined", "none"}:
                return value
    return None
