"""Turn uploaded files and fetched web pages into plain text for the assistant."""

import io
import logging
import re

import httpx
from fastapi.concurrency import run_in_threadpool
from selectolax.parser import HTMLParser

logger = logging.getLogger(__name__)

MAX_FETCH_BYTES = 5 * 1024 * 1024
_WS = re.compile(r"\n{3,}")


def _collapse(text: str) -> str:
    lines = [line.rstrip() for line in text.splitlines()]
    return _WS.sub("\n\n", "\n".join(lines)).strip()


def html_to_text(html: str) -> str:
    tree = HTMLParser(html)
    for tag in ("script", "style", "noscript", "nav", "footer", "header", "svg"):
        for node in tree.css(tag):
            node.decompose()
    body = tree.body or tree.root
    return _collapse(body.text(separator="\n") if body else "")


async def fetch_posting_text(url: str) -> str:
    """Fetch a job posting URL and reduce it to readable text.

    Many boards render postings client-side; when that happens the text comes back
    thin and the caller should fall back to a pasted description.
    """
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=20.0,
        headers={"User-Agent": "job-tracker/0.1 (+personal job search assistant)"},
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
        content = response.content[:MAX_FETCH_BYTES]
        content_type = response.headers.get("content-type", "")

    if "html" in content_type:
        return html_to_text(content.decode(response.encoding or "utf-8", errors="replace"))
    return _collapse(content.decode("utf-8", errors="replace"))


async def extract_document_text(data: bytes, content_type: str, filename: str) -> str | None:
    """Best-effort plain text from an upload. Returns None for unsupported formats."""
    lowered = filename.lower()

    if content_type == "application/pdf" or lowered.endswith(".pdf"):
        return await run_in_threadpool(_pdf_to_text, data)

    if content_type.startswith("text/") or lowered.endswith((".txt", ".md", ".markdown")):
        return _collapse(data.decode("utf-8", errors="replace"))

    if "html" in content_type or lowered.endswith((".html", ".htm")):
        return html_to_text(data.decode("utf-8", errors="replace"))

    # .docx and friends would need another dependency; store the file, skip the text.
    return None


def _pdf_to_text(data: bytes) -> str | None:
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        pages = [page.extract_text() or "" for page in reader.pages]
        text = _collapse("\n\n".join(pages))
        # A scanned PDF yields near-nothing; treat that as "no text" rather than
        # feeding the model a page of whitespace.
        return text if len(text) > 40 else None
    except Exception:
        logger.warning("PDF text extraction failed", exc_info=True)
        return None
