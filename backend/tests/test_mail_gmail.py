"""Tests for turning a Gmail API payload into something we can classify.

MIME flattening is where a mail integration quietly loses text: a multipart
message whose plain-text part is nested two levels down reads as empty, and an
empty body means every status phrase misses.
"""

import base64
from datetime import UTC, datetime

from app.mail.gmail import _body_text, _to_header, authorization_url


def encode(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def payload(**kwargs) -> dict:
    base = {
        "id": "18f2a",
        "threadId": "18f29",
        "internalDate": "1758326400000",
        "payload": {
            "headers": [
                {"name": "From", "value": "Acme Recruiting <recruiting@acmerobotics.com>"},
                {"name": "To", "value": "Alex <alex@example.com>"},
                {"name": "Subject", "value": "Your application"},
                {"name": "Date", "value": "Mon, 20 Sep 2026 12:00:00 +0000"},
            ]
        },
    }
    return {**base, **kwargs}


# ------------------------------------------------------------------------ headers


def test_header_parsing_splits_name_from_address():
    header = _to_header(payload())
    assert header.from_name == "Acme Recruiting"
    assert header.from_email == "recruiting@acmerobotics.com"
    assert header.to_email == "alex@example.com"
    assert header.subject == "Your application"
    assert header.thread_id == "18f29"


def test_a_bare_address_with_no_display_name_still_parses():
    header = _to_header(
        payload(payload={"headers": [{"name": "From", "value": "noreply@lever.co"}]})
    )
    assert header.from_name is None
    assert header.from_email == "noreply@lever.co"


def test_addresses_are_lowercased():
    header = _to_header(
        payload(payload={"headers": [{"name": "From", "value": "A <Recruiting@AcmeRobotics.com>"}]})
    )
    assert header.from_email == "recruiting@acmerobotics.com"


def test_receive_time_comes_from_gmail_not_the_sender():
    """A bulk sender's Date: header is sometimes days out; internalDate is not."""
    header = _to_header(
        payload(
            internalDate="1758326400000",
            payload={"headers": [{"name": "Date", "value": "Mon, 01 Jan 2020 00:00:00 +0000"}]},
        )
    )
    assert header.received_at == datetime.fromtimestamp(1758326400, tz=UTC)


def test_the_date_header_is_the_fallback():
    header = _to_header(
        payload(
            internalDate=None,
            payload={"headers": [{"name": "Date", "value": "Mon, 20 Sep 2026 12:00:00 +0000"}]},
        )
    )
    assert header.received_at == datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def test_a_missing_date_is_not_an_error():
    assert _to_header(payload(internalDate=None, payload={"headers": []})).received_at is None


def test_a_list_id_is_captured():
    header = _to_header(
        payload(payload={"headers": [{"name": "List-Id", "value": "<jobs.linkedin.com>"}]})
    )
    assert header.list_id == "<jobs.linkedin.com>"


# --------------------------------------------------------------------------- body


def test_a_plain_text_body_is_decoded():
    assert (
        _body_text({"mimeType": "text/plain", "body": {"data": encode("Hello there")}})
        == "Hello there"
    )


def test_an_html_only_body_is_reduced_to_text():
    html = "<html><body><p>We regret to inform you.</p><script>x()</script></body></html>"
    text = _body_text({"mimeType": "text/html", "body": {"data": encode(html)}})
    assert "We regret to inform you." in text
    assert "x()" not in text


def test_plain_text_wins_over_html_in_a_multipart_message():
    tree = {
        "mimeType": "multipart/alternative",
        "parts": [
            {"mimeType": "text/html", "body": {"data": encode("<p>HTML version</p>")}},
            {"mimeType": "text/plain", "body": {"data": encode("Plain version")}},
        ],
    }
    assert _body_text(tree) == "Plain version"


def test_a_nested_plain_text_part_is_found():
    """multipart/mixed wrapping multipart/alternative is the common real shape."""
    tree = {
        "mimeType": "multipart/mixed",
        "parts": [
            {
                "mimeType": "multipart/alternative",
                "parts": [
                    {"mimeType": "text/plain", "body": {"data": encode("Buried but findable")}},
                ],
            },
            {"mimeType": "application/pdf", "body": {"attachmentId": "abc"}},
        ],
    }
    assert _body_text(tree) == "Buried but findable"


def test_a_message_with_no_readable_part_returns_none():
    assert _body_text({"mimeType": "application/pdf", "body": {"attachmentId": "abc"}}) is None


def test_undecodable_data_does_not_raise():
    assert _body_text({"mimeType": "text/plain", "body": {"data": "!!!not base64!!!"}}) is None


# -------------------------------------------------------------------------- oauth


def test_the_consent_url_asks_for_read_access_and_a_refresh_token(monkeypatch):
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-123")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    url = authorization_url("state-abc")
    get_settings.cache_clear()

    assert "gmail.readonly" in url
    # Without these two Google skips the refresh token on re-consent, and the
    # mailbox would stop working an hour after it was connected.
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "state=state-abc" in url
    # Read-only means read-only: no modify, send or label scopes.
    assert "gmail.modify" not in url and "gmail.send" not in url


# ------------------------------------------------------- cross-mailbox identity


def test_the_senders_message_id_is_captured():
    """This is what makes one email reaching two mailboxes recognisable as one."""
    header = _to_header(
        payload(
            payload={"headers": [{"name": "Message-Id", "value": "<abc123@mail.acmerobotics.com>"}]}
        )
    )
    assert header.rfc822_message_id == "<abc123@mail.acmerobotics.com>"


def test_a_message_with_no_message_id_header_is_not_an_error():
    """Rare, but it happens; such a message just falls back to per-mailbox dedupe."""
    assert _to_header(payload(payload={"headers": []})).rfc822_message_id is None


def test_the_same_email_in_two_mailboxes_carries_one_message_id():
    """Gmail's own id differs per mailbox; the sender's does not."""
    in_personal = _to_header(
        payload(
            id="aaa",
            payload={"headers": [{"name": "Message-Id", "value": "<shared@acmerobotics.com>"}]},
        )
    )
    in_work = _to_header(
        payload(
            id="bbb",
            payload={"headers": [{"name": "Message-Id", "value": "<shared@acmerobotics.com>"}]},
        )
    )
    assert in_personal.provider_message_id != in_work.provider_message_id
    assert in_personal.rfc822_message_id == in_work.rfc822_message_id


# --------------------------------------------------------------- granted scopes


def test_a_grant_with_the_read_scope_is_usable():
    from app.mail.gmail import grants_mail_access

    assert grants_mail_access(
        "https://www.googleapis.com/auth/gmail.readonly openid "
        "https://www.googleapis.com/auth/userinfo.email"
    )


def test_a_grant_without_the_read_scope_is_refused():
    """Google issues a perfectly valid token that cannot read a single message."""
    from app.mail.gmail import grants_mail_access

    assert not grants_mail_access("https://www.googleapis.com/auth/userinfo.email openid")
    assert not grants_mail_access(None)
    assert not grants_mail_access("")


def test_a_lookalike_scope_does_not_count():
    from app.mail.gmail import grants_mail_access

    assert not grants_mail_access("https://www.googleapis.com/auth/gmail.readonly.something")
