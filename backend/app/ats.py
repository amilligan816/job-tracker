"""Resolve applicant-tracking-system URLs to the posting the browser would show.

Many company career pages are a thin shell around an ATS: the HTML served over
HTTP is navigation, cookie notices and EEO boilerplate, and the posting itself
is fetched by JavaScript after load. Scraping one of those pages is worse than
fetching nothing, because a page of footer text still looks like content -- the
extractor will dutifully assemble a "posting" out of the legal small print.

Where the ATS publishes the same posting over a public JSON API, we ask it
directly instead of scraping the shell.
"""

import logging
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

import httpx

logger = logging.getLogger(__name__)

_GREENHOUSE_API = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{job_id}"

# A Greenhouse board is addressed by a short token ("billtrust"), which an
# embedding page does not have to state anywhere machine-readable -- Billtrust,
# for one, passes it in `source` and reads it back in its own inline script. So
# we collect plausible tokens and let the API adjudicate: a wrong guess is a
# 404, and the first 200 is the answer.
_MAX_BOARD_GUESSES = 4

# Subdomains and suffixes that are never the board token.
_GENERIC_LABELS = frozenset(
    {"www", "careers", "career", "jobs", "job", "apply", "hire", "hiring", "work", "talent"}
)
_PUBLIC_SUFFIXES = frozenset(
    {"com", "org", "net", "io", "co", "ai", "dev", "app", "inc", "us", "uk", "eu", "de", "fr"}
)

# boards.greenhouse.io/acme/jobs/123 and job-boards.greenhouse.io/acme/jobs/123
_GREENHOUSE_PATH = re.compile(r"^/(?P<board>[A-Za-z0-9_-]+)/jobs/(?P<job_id>\d+)")


@dataclass(slots=True)
class AtsPosting:
    """A posting fetched from an ATS API, before it is flattened to text."""

    title: str
    company: str | None
    location: str | None
    employment_type: str | None
    content_html: str
    ats: str
    canonical_url: str | None = None


async def resolve_posting(url: str, client: httpx.AsyncClient | None = None) -> AtsPosting | None:
    """Return the posting behind an ATS URL, or None if this is not one we know.

    Never raises for a posting we simply could not resolve -- the caller falls
    back to scraping the page, which is the right answer for a career page that
    really does serve its postings as HTML.
    """
    board, job_id = _greenhouse_target(url)
    if not job_id:
        return None

    if client is not None:
        return await _greenhouse_fetch(client, board, job_id)
    async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as owned:
        return await _greenhouse_fetch(owned, board, job_id)


# ------------------------------------------------------------------------- greenhouse


def _greenhouse_target(url: str) -> tuple[list[str], str | None]:
    """Pull a job id and candidate board tokens out of a Greenhouse-ish URL."""
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    host = (parsed.hostname or "").lower()

    if host.endswith("greenhouse.io"):
        match = _GREENHOUSE_PATH.match(parsed.path)
        if match:
            return [match["board"]], match["job_id"]
        # The embed form: /embed/job_app?for=acme&token=123
        job_id = _first(params, "token", "gh_jid")
        return _board_candidates(params, host), job_id

    job_id = _first(params, "gh_jid")
    if not job_id:
        return [], None
    return _board_candidates(params, host), job_id


def _board_candidates(params: dict[str, list[str]], host: str) -> list[str]:
    """Board tokens worth trying, most explicit first."""
    candidates: list[str] = []

    def add(value: str | None) -> None:
        value = (value or "").strip().lower()
        if value and value not in candidates and re.fullmatch(r"[a-z0-9_-]+", value):
            candidates.append(value)

    # An explicit token in the query string beats anything guessed from the host.
    for key in ("for", "board", "gh_board", "source", "company"):
        add(_first(params, key))

    for label in host.split("."):
        if label not in _GENERIC_LABELS and label not in _PUBLIC_SUFFIXES:
            add(label)

    return candidates[:_MAX_BOARD_GUESSES]


async def _greenhouse_fetch(
    client: httpx.AsyncClient, boards: list[str], job_id: str
) -> AtsPosting | None:
    for board in boards:
        url = _GREENHOUSE_API.format(board=board, job_id=job_id)
        try:
            response = await client.get(url)
        except httpx.HTTPError:
            logger.warning("Greenhouse lookup failed for board %r", board, exc_info=True)
            continue
        if response.status_code == 404:
            continue
        if response.status_code >= 400:
            logger.warning("Greenhouse returned %s for board %r", response.status_code, board)
            continue
        try:
            posting = _greenhouse_posting(response.json())
        except (ValueError, TypeError, KeyError):
            logger.warning("Greenhouse payload was not a posting for %r", board, exc_info=True)
            continue
        if posting is not None:
            return posting
    return None


def _greenhouse_posting(data: dict) -> AtsPosting | None:
    title = (data.get("title") or "").strip()
    content = data.get("content") or ""
    if not title or not content:
        return None

    location = data.get("location") or {}
    metadata = data.get("metadata") or []
    employment = next(
        (
            str(item.get("value"))
            for item in metadata
            if isinstance(item, dict)
            and str(item.get("name", "")).lower() in {"employment type", "job type"}
            and item.get("value")
        ),
        None,
    )

    return AtsPosting(
        title=title,
        company=(data.get("company_name") or None),
        location=(location.get("name") if isinstance(location, dict) else None) or None,
        employment_type=employment,
        content_html=content,
        ats="greenhouse",
        canonical_url=data.get("absolute_url") or None,
    )


def _first(params: dict[str, list[str]], *keys: str) -> str | None:
    for key in keys:
        for value in params.get(key, []):
            value = value.strip()
            # Billtrust's own links carry `gh_src=null`; treat that as absent.
            if value and value.lower() not in {"null", "undefined", "none"}:
                return value
    return None
