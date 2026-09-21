"""Connecting a mailbox, syncing it, and reviewing what it proposed.

The one rule this module enforces: a sync never changes an application. Every
pipeline move goes through `accept`, which is a deliberate act by the user and
writes a timeline entry saying which email caused it.
"""

import hashlib
import hmac
import logging
import time
import uuid
from datetime import UTC, datetime
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.crud import get_or_404
from app.crypto import TokenKeyMissing, decrypt, encrypt
from app.db import get_db
from app.mail import gmail, sync
from app.models import (
    Application,
    ApplicationEvent,
    ApplicationStatus,
    EventKind,
    JobPosting,
    MailAccount,
    MailAccountStatus,
    MailMessage,
    MailProviderKind,
    MailSuggestion,
    SuggestionState,
)
from app.schemas import (
    MailAccountRead,
    MailAuthorization,
    MailStatus,
    MailSuggestionAccept,
    MailSuggestionRead,
    MailSyncResult,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/mail", tags=["mail"])

_SUGGESTION_OPTS = (
    selectinload(MailSuggestion.message).selectinload(MailMessage.account),
    selectinload(MailSuggestion.application)
    .selectinload(Application.posting)
    .selectinload(JobPosting.company),
)

# How long a half-finished OAuth round trip stays valid.
_STATE_TTL_SECONDS = 600


def _require_configured() -> None:
    if not get_settings().gmail_configured:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=(
                "Gmail is not configured. Set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET and "
                "MAIL_TOKEN_KEY, then restart the backend."
            ),
        )


# --------------------------------------------------------------------- status


@router.get("/status", response_model=MailStatus)
async def mail_status(db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    accounts = await db.execute(select(MailAccount).order_by(MailAccount.created_at))
    return MailStatus(
        configured=settings.gmail_configured,
        assistant_enabled=settings.assistant_enabled and settings.mail_use_claude,
        sync_interval_seconds=settings.mail_sync_interval_seconds,
        accounts=[MailAccountRead.model_validate(a) for a in accounts.scalars().all()],
        pending_suggestions=await sync.pending_suggestion_count(db),
    )


# ---------------------------------------------------------------------- oauth


@router.get("/oauth/google/start", response_model=MailAuthorization)
async def start_google_oauth():
    """Where to send the browser to grant read access to a Gmail account."""
    _require_configured()
    return MailAuthorization(authorization_url=gmail.authorization_url(_issue_state()))


@router.get("/oauth/google/callback", include_in_schema=False)
async def google_oauth_callback(
    db: AsyncSession = Depends(get_db),
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    """Where Google sends the user back.

    A browser lands here, not an API client, so every outcome is a redirect back
    into the app with a message rather than a JSON error nobody will see.
    """
    _require_configured()
    if error:
        return _back_to_app(error=f"Google returned: {error}")
    if not code or not state:
        return _back_to_app(error="Google's response was missing the authorization code.")
    if not _valid_state(state):
        # Either a stale tab or a request that did not start here.
        return _back_to_app(error="That sign-in link expired. Start the connection again.")

    try:
        tokens = await gmail.exchange_code(code)
        address = await gmail.fetch_email_address(tokens.access_token)
    except (gmail.GmailAuthError, gmail.GmailApiError) as exc:
        return _back_to_app(error=str(exc))

    if not gmail.grants_mail_access(tokens.scopes):
        # A token without the read scope looks fine and reads nothing. Refusing
        # here beats storing an account that 403s on its first sync.
        return _back_to_app(
            error=(
                "Google did not grant permission to read mail, so this mailbox was not "
                'connected. On the consent screen, leave "Read your email messages and '
                'settings" ticked. If it was never offered, add the gmail.readonly scope to '
                "the OAuth consent screen and enable the Gmail API in your Google Cloud project."
            )
        )

    if not tokens.refresh_token:
        # Without one we could read the mailbox for an hour and then silently
        # stop, which is worse than refusing now.
        return _back_to_app(
            error=(
                "Google did not issue a refresh token. Remove this app at "
                "https://myaccount.google.com/permissions and connect again."
            )
        )

    try:
        await _upsert_account(db, address, tokens)
    except TokenKeyMissing as exc:
        return _back_to_app(error=str(exc))

    return _back_to_app(connected=address)


async def _upsert_account(db: AsyncSession, address: str, tokens: gmail.TokenSet) -> MailAccount:
    """Connect the mailbox, or re-connect one we already knew about.

    Reconnecting keeps the row -- and so keeps every message and suggestion
    already filed under it -- and clears the error that prompted the reconnect.
    """
    existing = await db.execute(
        select(MailAccount).where(
            MailAccount.provider == MailProviderKind.gmail,
            MailAccount.email_address == address,
        )
    )
    account = existing.scalar_one_or_none()
    if account is None:
        account = MailAccount(provider=MailProviderKind.gmail, email_address=address)
        db.add(account)

    account.access_token = encrypt(tokens.access_token)
    account.refresh_token = encrypt(tokens.refresh_token) if tokens.refresh_token else None
    account.token_expires_at = tokens.expires_at
    account.scopes = tokens.scopes
    account.status = MailAccountStatus.active
    account.last_sync_error = None
    await db.flush()
    return account


def _back_to_app(*, connected: str | None = None, error: str | None = None) -> RedirectResponse:
    params = {"connected": connected} if connected else {"error": error or "Unknown error"}
    base = get_settings().frontend_base_url.rstrip("/")
    return RedirectResponse(f"{base}/email?{urlencode(params)}")


def _issue_state() -> str:
    """A signed, expiring state parameter.

    Signed rather than stored: the backend reloads on every code change in dev,
    and an in-memory set of pending states would lose them mid-flow.
    """
    issued = str(int(time.time()))
    return f"{issued}.{_sign(issued)}"


def _valid_state(state: str) -> bool:
    issued, _, signature = state.partition(".")
    if not issued or not signature or not hmac.compare_digest(signature, _sign(issued)):
        return False
    try:
        return time.time() - int(issued) < _STATE_TTL_SECONDS
    except ValueError:
        return False


def _sign(value: str) -> str:
    key = get_settings().mail_token_key.encode()
    return hmac.new(key, value.encode(), hashlib.sha256).hexdigest()


# -------------------------------------------------------------------- accounts


@router.get("/accounts", response_model=list[MailAccountRead])
async def list_accounts(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(MailAccount).order_by(MailAccount.created_at))
    return result.scalars().all()


@router.delete("/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_account(account_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Disconnect a mailbox and drop everything read from it.

    The messages go with it: they were only ever stored to support suggestions,
    and keeping a copy of someone's mail after they disconnect the account would
    be the wrong default.
    """
    account = await get_or_404(db, MailAccount, account_id)
    try:
        await gmail.revoke(decrypt(account.refresh_token or account.access_token))
    except Exception:  # noqa: BLE001 - local disconnection is what matters
        logger.warning("Could not revoke the Google grant for %s", account.email_address)
    await db.delete(account)


@router.post("/accounts/{account_id}/sync", response_model=MailSyncResult)
async def sync_now(account_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    account = await get_or_404(db, MailAccount, account_id)
    return await sync.sync_account(db, account)


@router.post("/sync", response_model=dict[str, MailSyncResult])
async def sync_everything(db: AsyncSession = Depends(get_db)):
    return await sync.sync_all(db)


# ----------------------------------------------------------------- suggestions


@router.get("/suggestions", response_model=list[MailSuggestionRead])
async def list_suggestions(
    db: AsyncSession = Depends(get_db),
    state: SuggestionState = Query(default=SuggestionState.pending),
    application_id: uuid.UUID | None = None,
    limit: int = Query(default=100, le=500),
):
    """The review queue.

    Bodies are left out here -- a page of suggestions would otherwise carry a
    page of email. `GET /mail/suggestions/{id}` has the full text.
    """
    stmt = (
        select(MailSuggestion)
        .options(*_SUGGESTION_OPTS)
        .where(MailSuggestion.state == state)
        .order_by(
            # Anything that proposes a move first, most confident first.
            MailSuggestion.suggested_status.isnot(None).desc(),
            MailSuggestion.confidence.desc(),
            MailSuggestion.created_at.desc(),
        )
        .limit(limit)
    )
    if application_id:
        stmt = stmt.where(MailSuggestion.application_id == application_id)

    result = await db.execute(stmt)
    return [_to_read(s, include_body=False) for s in result.scalars().all()]


@router.get("/suggestions/{suggestion_id}", response_model=MailSuggestionRead)
async def get_suggestion(suggestion_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    return _to_read(await _load_suggestion(db, suggestion_id), include_body=True)


@router.post("/suggestions/{suggestion_id}/accept", response_model=MailSuggestionRead)
async def accept_suggestion(
    suggestion_id: uuid.UUID,
    payload: MailSuggestionAccept,
    db: AsyncSession = Depends(get_db),
):
    """Apply a suggestion, optionally correcting it first.

    Accepting one that proposes no status change is still worth doing: it files
    the email against the application's timeline, which is where you go to
    remember what was actually said.
    """
    suggestion = await _load_suggestion(db, suggestion_id)
    if suggestion.state != SuggestionState.pending:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This suggestion was already {suggestion.state.value}.",
        )

    application_id = payload.application_id or suggestion.application_id
    if application_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This suggestion is not linked to an application; name one to accept it.",
        )
    application = await get_or_404(db, Application, application_id)
    new_status = payload.status or suggestion.suggested_status

    message = suggestion.message
    provenance = _provenance(message)

    if new_status is not None and new_status != application.status:
        previous = application.status
        application.status = new_status
        if new_status == ApplicationStatus.applied and application.applied_on is None:
            application.applied_on = datetime.now(UTC).date()
        db.add(
            ApplicationEvent(
                application_id=application.id,
                kind=EventKind.status_change,
                summary=f"{previous.value} -> {new_status.value} (from email)",
                detail=provenance,
                occurred_at=message.received_at or datetime.now(UTC),
            )
        )
    else:
        new_status = None
        db.add(
            ApplicationEvent(
                application_id=application.id,
                kind=EventKind.email,
                summary=(message.subject or "Email received")[:512],
                detail=provenance,
                occurred_at=message.received_at or datetime.now(UTC),
            )
        )

    suggestion.application_id = application.id
    suggestion.suggested_status = new_status
    suggestion.state = SuggestionState.accepted
    suggestion.resolved_at = datetime.now(UTC)
    await db.flush()
    return _to_read(await _load_suggestion(db, suggestion_id), include_body=True)


@router.post("/suggestions/{suggestion_id}/dismiss", response_model=MailSuggestionRead)
async def dismiss_suggestion(suggestion_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    suggestion = await _load_suggestion(db, suggestion_id)
    suggestion.state = SuggestionState.dismissed
    suggestion.resolved_at = datetime.now(UTC)
    await db.flush()
    return _to_read(await _load_suggestion(db, suggestion_id), include_body=True)


# ----------------------------------------------------------------------- helpers


async def _load_suggestion(db: AsyncSession, suggestion_id: uuid.UUID) -> MailSuggestion:
    result = await db.execute(
        select(MailSuggestion).options(*_SUGGESTION_OPTS).where(MailSuggestion.id == suggestion_id)
    )
    suggestion = result.scalar_one_or_none()
    if suggestion is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Suggestion {suggestion_id} not found"
        )
    return suggestion


def _provenance(message) -> str:
    """The email, quoted into the timeline entry.

    A status change you do not recognise six weeks later is a support ticket to
    yourself; the sender, date and subject make it answerable.
    """
    sender = message.from_name or message.from_email or "unknown sender"
    when = message.received_at.strftime("%Y-%m-%d") if message.received_at else "unknown date"
    subject = message.subject or "(no subject)"
    return f"From {sender} <{message.from_email or '?'}> on {when}\nSubject: {subject}"


def _to_read(suggestion: MailSuggestion, *, include_body: bool) -> MailSuggestionRead:
    read = MailSuggestionRead.model_validate(suggestion)
    if not include_body:
        read.message.body_text = None
    if suggestion.message.account is not None:
        read.account_email = suggestion.message.account.email_address

    application = suggestion.application
    if application is not None:
        read.current_status = application.status
        posting = application.posting
        if posting is not None:
            read.posting_title = posting.title
            read.company_name = posting.company.name if posting.company else None
    return read
