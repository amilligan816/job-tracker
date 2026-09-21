"""Google OAuth and the Gmail REST API.

Spoken over httpx rather than google-api-python-client: the surface we need is
four endpoints, and the official client is sync-only, which would mean a thread
pool around every call in an otherwise async service.

Scope is `gmail.readonly` and nothing else. This feature reads mail; it never
sends, labels, archives or deletes, and the consent screen should say so.
"""

import base64
import html
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parseaddr, parsedate_to_datetime
from urllib.parse import urlencode

import httpx

from app.config import get_settings
from app.mail.provider import HeaderPage, MessageBody, MessageHeader
from app.textextract import html_to_text

logger = logging.getLogger(__name__)

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
API_ROOT = "https://gmail.googleapis.com/gmail/v1/users/me"

READ_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
SCOPES = (READ_SCOPE, "openid", "email")

# Headers worth asking for in the cheap first pass.
_METADATA_HEADERS = ("From", "To", "Subject", "Date", "Message-Id", "List-Id")

# Chats and drafts are not mail anyone sent us about a job.
_BASE_QUERY = "-in:chats -in:drafts"

_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
# Bodies are fetched one request each; this keeps a backfill polite.
_BODY_CONCURRENCY = 5


class GmailAuthError(RuntimeError):
    """The grant is gone -- revoked, expired past refresh, or never issued."""


class GmailApiError(RuntimeError):
    """Gmail answered, but not with what we asked for."""


def grants_mail_access(granted_scopes: str | None) -> bool:
    """Whether a grant actually lets us read mail.

    Google will hand back a token carrying only `openid` and `userinfo.email`
    when the Gmail scope was not consented to -- which is a working token that
    cannot read a single message. Checking here turns that into one clear
    message at connect time instead of a 403 on the first sync.
    """
    return READ_SCOPE in (granted_scopes or "").split()


@dataclass(slots=True)
class TokenSet:
    access_token: str
    refresh_token: str | None
    expires_at: datetime | None
    scopes: str | None


# ------------------------------------------------------------------------ OAuth


def authorization_url(state: str) -> str:
    """The consent screen to send the user to.

    `access_type=offline` with `prompt=consent` is what makes Google hand back a
    refresh token. Google omits it on re-consent otherwise, which would leave the
    account working until the first access token expired and then quietly stop.
    """
    settings = get_settings()
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


async def exchange_code(code: str) -> TokenSet:
    settings = get_settings()
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": settings.google_redirect_uri,
                "grant_type": "authorization_code",
            },
        )
    return _token_set(response)


async def refresh_access_token(refresh_token: str) -> TokenSet:
    settings = get_settings()
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.post(
            TOKEN_URL,
            data={
                "refresh_token": refresh_token,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "grant_type": "refresh_token",
            },
        )
    tokens = _token_set(response)
    # A refresh response carries no refresh_token; the existing one stands.
    return TokenSet(tokens.access_token, refresh_token, tokens.expires_at, tokens.scopes)


async def fetch_email_address(access_token: str) -> str:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.get(
            USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}
        )
    if response.status_code != 200:
        raise GmailApiError(f"Could not read the Google account profile ({response.status_code})")
    address = response.json().get("email")
    if not address:
        raise GmailApiError("Google did not return an email address for this account.")
    return address


async def revoke(token: str) -> None:
    """Best-effort revocation.

    Disconnecting locally is the part that matters; if Google is unreachable we
    still drop our copy rather than leave a half-connected account behind.
    """
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            await client.post(REVOKE_URL, data={"token": token})
    except httpx.HTTPError:
        logger.warning("Could not revoke the Google token; removing it locally anyway")


def _token_set(response: httpx.Response) -> TokenSet:
    if response.status_code != 200:
        detail = _error_detail(response)
        if response.status_code in (400, 401):
            raise GmailAuthError(f"Google rejected the credentials: {detail}")
        raise GmailApiError(f"Google token endpoint failed ({response.status_code}): {detail}")

    payload = response.json()
    expires_in = payload.get("expires_in")
    return TokenSet(
        access_token=payload["access_token"],
        refresh_token=payload.get("refresh_token"),
        expires_at=(datetime.now(UTC) + timedelta(seconds=int(expires_in)) if expires_in else None),
        scopes=payload.get("scope"),
    )


def _error_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:200]
    error = body.get("error")
    description = body.get("error_description") or (
        error.get("message") if isinstance(error, dict) else None
    )
    return description or (error if isinstance(error, str) else response.text[:200])


# ------------------------------------------------------------------------ provider


class GmailProvider:
    """Reads one connected mailbox.

    Holds a live access token and refreshes it in place; `on_token_refresh` is
    how the caller persists the new one, since it is the caller that owns the
    database row.
    """

    def __init__(
        self,
        *,
        access_token: str,
        refresh_token: str | None,
        expires_at: datetime | None = None,
        on_token_refresh=None,
    ):
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._expires_at = expires_at
        self._on_token_refresh = on_token_refresh
        self._client = httpx.AsyncClient(timeout=_TIMEOUT)

    async def aclose(self) -> None:
        await self._client.aclose()

    # -- requests ---------------------------------------------------------

    async def _ensure_token(self) -> None:
        """Refresh ahead of expiry rather than on the 401.

        A minute of slack covers clock skew and a long-running backfill that
        started while the token was still technically valid.
        """
        if self._expires_at is None:
            # Expiry unknown; ride it until a 401 forces the issue.
            return
        if self._expires_at - timedelta(minutes=1) > datetime.now(UTC):
            return
        await self._refresh()

    async def _refresh(self) -> None:
        if not self._refresh_token:
            raise GmailAuthError(
                "This mailbox has no refresh token, so its access cannot be renewed. "
                "Reconnect the account."
            )
        tokens = await refresh_access_token(self._refresh_token)
        self._access_token = tokens.access_token
        self._expires_at = tokens.expires_at
        if self._on_token_refresh:
            await self._on_token_refresh(tokens)

    async def _get(self, path: str, params=None, *, retry: bool = True) -> dict:
        """GET one Gmail endpoint.

        `params` is anything httpx accepts -- a dict, or a list of pairs when a
        key repeats, as `metadataHeaders` does.
        """
        await self._ensure_token()
        response = await self._client.get(
            f"{API_ROOT}{path}",
            params=params,
            headers={"Authorization": f"Bearer {self._access_token}"},
        )
        if response.status_code == 401 and retry:
            # The token died earlier than its stated expiry -- password change,
            # revoked session. One refresh, then take the answer at face value.
            await self._refresh()
            return await self._get(path, params, retry=False)
        if response.status_code in (401, 403):
            detail = _error_detail(response)
            if "insufficient authentication scopes" in detail.lower():
                raise GmailAuthError(
                    "This mailbox was connected without permission to read mail. Reconnect it "
                    "and make sure the Gmail permission stays ticked on Google's consent screen."
                )
            raise GmailAuthError(f"Gmail refused the request: {detail}")
        if response.status_code == 404:
            raise GmailApiError("not-found")
        if response.status_code != 200:
            raise GmailApiError(
                f"Gmail request failed ({response.status_code}): {_error_detail(response)}"
            )
        return response.json()

    # -- provider interface ------------------------------------------------

    async def load_headers(
        self, *, cursor: str | None, lookback_days: int, limit: int
    ) -> HeaderPage:
        ids, next_cursor, truncated = (
            await self._ids_since(cursor, limit)
            if cursor
            else await self._ids_in_window(lookback_days, limit)
        )
        headers = [h for mid in ids if (h := await self._header(mid))]
        return HeaderPage(headers=headers, cursor=next_cursor, truncated=truncated)

    async def load_body(self, provider_message_id: str) -> MessageBody:
        payload = await self._get(f"/messages/{provider_message_id}", {"format": "full"})
        return MessageBody(
            snippet=_unescape_snippet(payload.get("snippet")),
            body_text=_body_text(payload.get("payload") or {}),
        )

    # -- listing -----------------------------------------------------------

    async def _ids_in_window(
        self, lookback_days: int, limit: int
    ) -> tuple[list[str], str | None, bool]:
        """Backfill: every message in the lookback window, newest first."""
        ids: list[str] = []
        page_token: str | None = None
        query = f"{_BASE_QUERY} newer_than:{max(lookback_days, 1)}d"

        while len(ids) < limit:
            params = {"q": query, "maxResults": min(500, limit - len(ids))}
            if page_token:
                params["pageToken"] = page_token
            payload = await self._get("/messages", params)
            ids.extend(m["id"] for m in payload.get("messages", []))
            page_token = payload.get("nextPageToken")
            if not page_token:
                break

        truncated = len(ids) >= limit and bool(page_token)
        # The cursor comes from the profile, not the listing: it marks "caught up
        # as of now", which is exactly what the next incremental sync wants. On a
        # truncated backfill it is held back so nothing is skipped.
        cursor = None if truncated else await self.current_history_id()
        return ids[:limit], cursor, truncated

    async def _ids_since(self, cursor: str, limit: int) -> tuple[list[str], str | None, bool]:
        """Incremental: what Gmail's history says has arrived since `cursor`."""
        ids: list[str] = []
        page_token: str | None = None
        latest = cursor

        while len(ids) < limit:
            params: dict = {
                "startHistoryId": cursor,
                "historyTypes": "messageAdded",
                "maxResults": 500,
            }
            if page_token:
                params["pageToken"] = page_token
            try:
                payload = await self._get("/history", params)
            except GmailApiError as exc:
                if str(exc) == "not-found":
                    # The cursor aged out of Gmail's history window (it keeps
                    # roughly a week). Fall back to a window scan.
                    logger.info("Gmail history cursor expired; falling back to a window backfill")
                    settings = get_settings()
                    return await self._ids_in_window(settings.mail_lookback_days, limit)
                raise

            latest = payload.get("historyId") or latest
            for record in payload.get("history", []):
                for added in record.get("messagesAdded", []):
                    message = added.get("message", {})
                    label_ids = message.get("labelIds") or []
                    if "DRAFT" in label_ids or "CHAT" in label_ids or "SENT" in label_ids:
                        continue
                    if message.get("id"):
                        ids.append(message["id"])

            page_token = payload.get("nextPageToken")
            if not page_token:
                break

        truncated = len(ids) > limit
        if truncated:
            # Hold the cursor so the overflow is picked up next run.
            return ids[:limit], cursor, True
        # History can report the same message more than once; dedupe, keep order.
        return list(dict.fromkeys(ids)), latest, False

    async def current_history_id(self) -> str | None:
        payload = await self._get("/profile")
        history_id = payload.get("historyId")
        return str(history_id) if history_id else None

    async def _header(self, message_id: str) -> MessageHeader | None:
        params = [("format", "metadata")] + [("metadataHeaders", h) for h in _METADATA_HEADERS]
        try:
            payload = await self._get(f"/messages/{message_id}", params)
        except GmailApiError as exc:
            if str(exc) == "not-found":
                # Deleted between the listing and now.
                return None
            raise
        return _to_header(payload)


def _to_header(payload: dict) -> MessageHeader:
    headers = {
        h.get("name", "").lower(): h.get("value", "")
        for h in (payload.get("payload") or {}).get("headers", [])
    }
    from_name, from_email = parseaddr(headers.get("from", ""))
    _, to_email = parseaddr(headers.get("to", ""))
    return MessageHeader(
        provider_message_id=payload["id"],
        rfc822_message_id=headers.get("message-id") or None,
        thread_id=payload.get("threadId"),
        from_email=from_email.lower() or None,
        from_name=from_name or None,
        to_email=to_email.lower() or None,
        subject=headers.get("subject") or None,
        received_at=_received_at(payload, headers.get("date")),
        list_id=headers.get("list-id") or None,
    )


def _received_at(payload: dict, date_header: str | None) -> datetime | None:
    """Prefer Gmail's own receive time over the sender's Date: header.

    `internalDate` is when Gmail got it; `Date:` is whatever the sender's clock
    said, which on bulk mail is sometimes days off.
    """
    internal = payload.get("internalDate")
    if internal:
        try:
            return datetime.fromtimestamp(int(internal) / 1000, tz=UTC)
        except (ValueError, OverflowError, OSError):
            pass
    if date_header:
        try:
            parsed = parsedate_to_datetime(date_header)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except (TypeError, ValueError):
            pass
    return None


def _unescape_snippet(snippet: str | None) -> str | None:
    if not snippet:
        return None
    return html.unescape(snippet)


def _body_text(payload: dict, depth: int = 0) -> str | None:
    """Flatten a MIME tree to readable text.

    text/plain wins where a message carries both; otherwise the HTML part goes
    through the same reducer the posting fetcher uses.
    """
    if depth > 10:
        return None

    mime_type = payload.get("mimeType", "")
    body = payload.get("body") or {}
    data = body.get("data")

    if data and mime_type == "text/plain":
        return _decode(data)
    if data and mime_type == "text/html":
        decoded = _decode(data)
        return html_to_text(decoded) if decoded else None

    parts = payload.get("parts") or []
    for part in parts:
        if part.get("mimeType") == "text/plain" and (text := _body_text(part, depth + 1)):
            return text
    for part in parts:
        text = _body_text(part, depth + 1)
        if text:
            return text
    return None


def _decode(data: str) -> str | None:
    try:
        return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode(
            "utf-8", errors="replace"
        )
    except (ValueError, TypeError):
        return None
