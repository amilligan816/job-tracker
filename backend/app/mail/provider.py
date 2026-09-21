"""What a mailbox has to look like to be syncable.

Gmail is the only implementation today. The interface exists because the sync
loop, the classifier and the routes should not learn a second provider's
vocabulary when Outlook or IMAP arrives -- they deal in `MessageHeader` and
`MessageBody`, and a provider translates.

The two-stage shape is deliberate: headers are cheap and most of them are not
job mail, so the classifier gets a first look at sender and subject alone, and
only messages that survive that gate cost a body fetch.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(slots=True)
class MessageHeader:
    """Enough of a message to decide whether it is worth reading properly."""

    provider_message_id: str
    # The sender's own `Message-Id`. Stable across mailboxes, unlike the
    # provider's id, so it is how we recognise one email arriving twice.
    rfc822_message_id: str | None = None
    thread_id: str | None = None
    from_email: str | None = None
    from_name: str | None = None
    to_email: str | None = None
    subject: str | None = None
    received_at: datetime | None = None
    # Set on bulk mail. A posting alert blast and a recruiter's reply look alike
    # by subject alone; this is one of the few honest ways to tell them apart.
    list_id: str | None = None


@dataclass(slots=True)
class MessageBody:
    snippet: str | None = None
    body_text: str | None = None


@dataclass(slots=True)
class HeaderPage:
    headers: list[MessageHeader]
    # Where the next sync should resume from. Persisted only after the run
    # succeeds, so a crash mid-run replays rather than skips.
    cursor: str | None = None
    # True when the per-run ceiling cut the list short. The cursor is then held
    # back, so the next run picks up the remainder instead of losing it.
    truncated: bool = False


class MailProvider(Protocol):
    async def load_headers(
        self, *, cursor: str | None, lookback_days: int, limit: int
    ) -> HeaderPage:
        """Headers for everything new since `cursor`.

        With no cursor this is a backfill over `lookback_days`.
        """
        ...

    async def load_body(self, provider_message_id: str) -> MessageBody: ...

    async def aclose(self) -> None: ...
