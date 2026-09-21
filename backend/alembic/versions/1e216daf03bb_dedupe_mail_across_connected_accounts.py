"""dedupe mail across connected accounts

Records the sender's own `Message-Id` alongside the provider's per-mailbox id,
so one email addressed to two connected accounts is recognised as one thing to
review rather than two.

Existing rows keep a null here; they were stored before the column existed and
are already deduped within their own mailbox.

Revision ID: 1e216daf03bb
Revises: 54be5c55ef23
Create Date: 2026-09-20 21:43:50.662975
"""

from alembic import op
import sqlalchemy as sa


revision = "1e216daf03bb"
down_revision = "54be5c55ef23"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mail_messages", sa.Column("rfc822_message_id", sa.String(length=998), nullable=True)
    )
    op.create_index(
        op.f("ix_mail_messages_rfc822_message_id"),
        "mail_messages",
        ["rfc822_message_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_mail_messages_rfc822_message_id"), table_name="mail_messages")
    op.drop_column("mail_messages", "rfc822_message_id")
