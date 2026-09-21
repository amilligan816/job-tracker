"""One pass over a connected mailbox.

The funnel, and why it is shaped this way:

    list headers        cheap, one request per page
      -> stage-one gate most of an inbox dies here, unread
      -> fetch body     a request each, so only for what survived
      -> classify       deterministic; Claude only for the unclear ones
      -> persist        messages we linked, and a suggestion each

Nothing in here touches an application. A sync produces proposals; accepting one
is a separate, deliberate act in `app/routers/mail.py`.
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.crypto import TokenUnreadable, decrypt, encrypt
from app.mail import classify
from app.mail.classify import ApplicationTarget, Verdict
from app.mail.gmail import GmailAuthError, GmailProvider, TokenSet
from app.mail.provider import MailProvider, MessageBody, MessageHeader
from app.models import (
    MailAccount,
    MailAccountStatus,
    MailMessage,
    MailSuggestion,
    SuggestionSource,
    SuggestionState,
)
from app.schemas import MailSyncResult

logger = logging.getLogger(__name__)

# Bodies are one request each; a handful at a time keeps a backfill from looking
# like an attack while still being much faster than serial fetching.
_BODY_CONCURRENCY = 5

# Only this much of a body is kept. Enough to review the email in the UI and to
# re-classify later, without turning Postgres into a mail store.
_STORED_BODY_CHARS = 20_000


async def sync_account(db: AsyncSession, account: MailAccount) -> MailSyncResult:
    """Fetch, classify and file everything new in one mailbox."""
    settings = get_settings()
    try:
        provider = await _provider_for(db, account)
    except TokenUnreadable as exc:
        return await _record_failure(db, account, str(exc), MailAccountStatus.needs_reauth)

    targets = await classify.build_targets(db)
    try:
        page = await provider.load_headers(
            cursor=account.sync_cursor,
            lookback_days=settings.mail_lookback_days,
            limit=settings.mail_max_messages_per_sync,
        )
        result = await _process(db, account, provider, page.headers, targets)
        result.truncated = page.truncated
    except GmailAuthError as exc:
        return await _record_failure(db, account, str(exc), MailAccountStatus.needs_reauth)
    except Exception as exc:  # noqa: BLE001 - the run's outcome is data, not a crash
        logger.exception("Mail sync failed for %s", account.email_address)
        return await _record_failure(db, account, str(exc), MailAccountStatus.error)
    finally:
        await provider.aclose()

    account.status = MailAccountStatus.active
    account.last_synced_at = datetime.now(UTC)
    account.last_sync_error = None
    account.last_sync_stats = result.model_dump(exclude={"error"})
    # Held back on a truncated run so the overflow is picked up next time.
    if page.cursor and not page.truncated:
        account.sync_cursor = page.cursor
    await db.flush()
    return result


async def sync_all(db: AsyncSession) -> dict[str, MailSyncResult]:
    """Sync every connected mailbox that is not waiting on the user."""
    result = await db.execute(
        select(MailAccount).where(MailAccount.status != MailAccountStatus.needs_reauth)
    )
    return {
        account.email_address: await sync_account(db, account) for account in result.scalars().all()
    }


# ----------------------------------------------------------------------- the pass


async def _process(
    db: AsyncSession,
    account: MailAccount,
    provider: MailProvider,
    headers: list[MessageHeader],
    targets: list[ApplicationTarget],
) -> MailSyncResult:
    result = MailSyncResult(scanned=len(headers))
    if not headers:
        return result

    known = await _known_message_ids(db, account.id, [h.provider_message_id for h in headers])
    fresh = [h for h in headers if h.provider_message_id not in known]
    # A recruiter who mails both of your addresses, or one mailbox forwarding to
    # another, would otherwise land in the review queue twice.
    seen_elsewhere = await _known_rfc822_ids(db, [h.rfc822_message_id for h in fresh])
    fresh = [h for h in fresh if h.rfc822_message_id not in seen_elsewhere]
    if not fresh:
        return result

    threads = await _thread_links(db, account.id, [h.thread_id for h in fresh if h.thread_id])

    worth_reading: list[MessageHeader] = []
    seen_in_run: set[str] = set()
    for header in fresh:
        if header.rfc822_message_id and header.rfc822_message_id in seen_in_run:
            continue
        if classify.is_worth_reading(header, targets, threads.get(header.thread_id or "")):
            worth_reading.append(header)
            if header.rfc822_message_id:
                seen_in_run.add(header.rfc822_message_id)
    bodies = await _load_bodies(provider, worth_reading)

    for header in worth_reading:
        body = bodies.get(header.provider_message_id)
        if body is None:
            continue

        thread_application = threads.get(header.thread_id or "")
        verdict = classify.classify(header, body, targets, thread_application)
        verdict = await _maybe_refine(header, body, targets, verdict)
        if verdict is None or verdict.application_id is None:
            continue

        message = _store_message(db, account, header, body)
        await db.flush()
        db.add(_store_suggestion(message.id, verdict))
        result.stored += 1
        if verdict.suggested_status is not None:
            result.suggested += 1

        # A linked message teaches the rest of its thread where it belongs.
        if header.thread_id:
            threads[header.thread_id] = verdict.application_id

    await db.flush()
    return result


async def _load_bodies(
    provider: MailProvider, headers: list[MessageHeader]
) -> dict[str, MessageBody]:
    semaphore = asyncio.Semaphore(_BODY_CONCURRENCY)

    async def one(header: MessageHeader) -> tuple[str, MessageBody | None]:
        async with semaphore:
            try:
                return header.provider_message_id, await provider.load_body(
                    header.provider_message_id
                )
            except GmailAuthError:
                raise
            except Exception:  # noqa: BLE001 - one unreadable message is not a failed run
                logger.warning("Could not read message %s; skipping it", header.provider_message_id)
                return header.provider_message_id, None

    pairs = await asyncio.gather(*(one(h) for h in headers))
    return {mid: body for mid, body in pairs if body is not None}


async def _maybe_refine(
    header: MessageHeader,
    body: MessageBody,
    targets: list[ApplicationTarget],
    verdict: Verdict | None,
) -> Verdict | None:
    """Hand the unclear ones to Claude, when there is a credential for it.

    "Unclear" is either no deterministic match at all, or a match we are not
    confident in. A confident heuristic verdict is left alone: it is free, it is
    reproducible, and paying for a second opinion on it buys nothing.
    """
    settings = get_settings()
    if not (settings.mail_use_claude and settings.assistant_enabled):
        return verdict
    if verdict is not None and verdict.confidence >= settings.mail_claude_confidence_floor:
        return verdict

    candidates = classify.shortlist(header, body, targets)
    if not candidates:
        return verdict

    # Imported here so a missing/disabled assistant never weighs on module import.
    from app.llm import AssistantUnavailable, classify_email

    try:
        parsed, _ = await classify_email(
            subject=header.subject,
            sender=header.from_email,
            body=body.body_text or body.snippet,
            candidates=[classify.describe(t) for t in candidates],
        )
    except AssistantUnavailable:
        return verdict
    except Exception:  # noqa: BLE001 - a second opinion failing leaves the first standing
        logger.warning("Claude could not triage a message; keeping the heuristic verdict")
        return verdict

    index = parsed.application_index
    if index is None or not 0 <= index < len(candidates):
        # The model declined to match, or pointed outside the list. Either way it
        # has not given us an application, so the heuristic verdict stands.
        return verdict

    target = candidates[index]
    status = classify.guard_transition(target.status, parsed.status)
    return Verdict(
        application_id=target.application_id,
        suggested_status=status,
        confidence=round(parsed.confidence if status else parsed.confidence * 0.5, 3),
        reasoning=parsed.reasoning,
        source=SuggestionSource.claude,
        signals={
            "matched_on": ["Claude read the email"],
            # Kept so a surprising suggestion can be traced back to what the
            # string matching thought before Claude was asked.
            "heuristic": (
                {"status": verdict.suggested_status, "confidence": verdict.confidence}
                if verdict
                else None
            ),
        },
    )


# ---------------------------------------------------------------------- persisting


def _store_message(
    db: AsyncSession, account: MailAccount, header: MessageHeader, body: MessageBody
) -> MailMessage:
    message = MailMessage(
        account_id=account.id,
        provider_message_id=header.provider_message_id,
        rfc822_message_id=header.rfc822_message_id,
        thread_id=header.thread_id,
        from_email=header.from_email,
        from_name=header.from_name,
        to_email=header.to_email,
        subject=header.subject,
        snippet=body.snippet,
        body_text=(body.body_text or "")[:_STORED_BODY_CHARS] or None,
        received_at=header.received_at,
    )
    db.add(message)
    return message


def _store_suggestion(message_id: uuid.UUID, verdict: Verdict) -> MailSuggestion:
    return MailSuggestion(
        message_id=message_id,
        application_id=verdict.application_id,
        suggested_status=verdict.suggested_status,
        confidence=verdict.confidence,
        source=verdict.source,
        reasoning=verdict.reasoning,
        signals=_jsonable(verdict.signals),
    )


def _jsonable(value):
    """Turn enums into their values so JSONB will take the structure."""
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value.value if hasattr(value, "value") else value


# -------------------------------------------------------------------- lookups etc


async def _known_message_ids(
    db: AsyncSession, account_id: uuid.UUID, provider_ids: list[str]
) -> set[str]:
    if not provider_ids:
        return set()
    result = await db.execute(
        select(MailMessage.provider_message_id).where(
            MailMessage.account_id == account_id,
            MailMessage.provider_message_id.in_(provider_ids),
        )
    )
    return set(result.scalars().all())


async def _known_rfc822_ids(db: AsyncSession, message_ids: list[str | None]) -> set[str]:
    """Which of these emails we already hold, under *any* connected mailbox.

    Deliberately not scoped to one account: that is the whole point. The sender
    set this id, so the same email reaching two addresses carries it twice.
    """
    wanted = {mid for mid in message_ids if mid}
    if not wanted:
        return set()
    result = await db.execute(
        select(MailMessage.rfc822_message_id).where(MailMessage.rfc822_message_id.in_(wanted))
    )
    return set(result.scalars().all())


async def _thread_links(
    db: AsyncSession, account_id: uuid.UUID, thread_ids: list[str]
) -> dict[str, uuid.UUID]:
    """Which application each of these threads was already filed under.

    Thread continuity is the strongest signal there is: a recruiter's fourth
    reply rarely names the company again, but it is unambiguously about the same
    job as the first.
    """
    if not thread_ids:
        return {}
    result = await db.execute(
        select(MailMessage.thread_id, MailSuggestion.application_id)
        .join(MailSuggestion, MailSuggestion.message_id == MailMessage.id)
        .where(
            MailMessage.account_id == account_id,
            MailMessage.thread_id.in_(set(thread_ids)),
            MailSuggestion.application_id.isnot(None),
        )
    )
    return {thread_id: application_id for thread_id, application_id in result.all()}


async def pending_suggestion_count(db: AsyncSession) -> int:
    result = await db.execute(
        select(func.count(MailSuggestion.id)).where(MailSuggestion.state == SuggestionState.pending)
    )
    return result.scalar_one()


async def _provider_for(db: AsyncSession, account: MailAccount) -> MailProvider:
    async def persist(tokens: TokenSet) -> None:
        account.access_token = encrypt(tokens.access_token)
        account.token_expires_at = tokens.expires_at
        await db.flush()

    return GmailProvider(
        access_token=decrypt(account.access_token),
        refresh_token=decrypt(account.refresh_token) if account.refresh_token else None,
        expires_at=account.token_expires_at,
        on_token_refresh=persist,
    )


async def _record_failure(
    db: AsyncSession, account: MailAccount, message: str, status: MailAccountStatus
) -> MailSyncResult:
    account.status = status
    account.last_sync_error = message
    account.last_synced_at = datetime.now(UTC)
    await db.flush()
    return MailSyncResult(error=message)
