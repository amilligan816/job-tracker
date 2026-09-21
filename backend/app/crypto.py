"""Symmetric encryption for the OAuth tokens we have to keep.

A refresh token is a long-lived credential to someone's mailbox, so it does not
sit in Postgres in the clear. One Fernet key out of the environment covers it --
this is a single-user, self-hosted app, so key rotation and per-record keys would
be machinery without a threat model to justify them.
"""

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


class TokenKeyMissing(RuntimeError):
    """No MAIL_TOKEN_KEY set, so there is nowhere safe to put a token."""


class TokenUnreadable(RuntimeError):
    """Stored ciphertext will not decrypt under the configured key."""


@lru_cache
def _fernet() -> Fernet:
    key = get_settings().mail_token_key
    if not key:
        raise TokenKeyMissing(
            "Connecting a mailbox needs MAIL_TOKEN_KEY set to a Fernet key. Generate one with:\n"
            '  python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        )
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as exc:
        raise TokenKeyMissing(
            "MAIL_TOKEN_KEY is not a valid Fernet key (32 url-safe base64-encoded bytes)."
        ) from exc


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    """Reverse `encrypt`.

    A key that changed after the tokens were written lands here; the account has
    to be reconnected, which is what the caller turns this into.
    """
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise TokenUnreadable(
            "Stored token could not be decrypted -- MAIL_TOKEN_KEY has changed since it was "
            "saved. Reconnect the mailbox."
        ) from exc
