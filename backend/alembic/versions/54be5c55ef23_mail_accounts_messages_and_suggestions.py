"""mail accounts, messages and suggestions

Adds the three tables the Gmail integration needs -- the connected account, the
messages worth keeping, and the pipeline updates they propose -- plus an `email`
kind on the application timeline for mail that is filed without a status change.

Revision ID: 54be5c55ef23
Revises: 618c72959ded
Create Date: 2026-09-20 21:16:58.872836
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "54be5c55ef23"
down_revision = "618c72959ded"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Mail filed against an application without moving it gets its own timeline
    # kind. Postgres 12+ takes this inside a transaction as long as nothing in
    # the same transaction uses the new value -- nothing here does.
    op.execute("ALTER TYPE event_kind ADD VALUE IF NOT EXISTS 'email'")

    op.create_table(
        "mail_accounts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.Enum("gmail", name="mail_provider_kind"), nullable=False),
        sa.Column("email_address", sa.String(length=320), nullable=False),
        sa.Column("access_token", sa.Text(), nullable=False),
        sa.Column("refresh_token", sa.Text(), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scopes", sa.String(length=1024), nullable=True),
        sa.Column("sync_cursor", sa.String(length=64), nullable=True),
        sa.Column(
            "status",
            sa.Enum("active", "needs_reauth", "error", name="mail_account_status"),
            nullable=False,
        ),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_error", sa.Text(), nullable=True),
        sa.Column("last_sync_stats", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_mail_accounts_provider_address",
        "mail_accounts",
        ["provider", "email_address"],
        unique=True,
    )
    op.create_table(
        "mail_messages",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("account_id", sa.UUID(), nullable=False),
        sa.Column("provider_message_id", sa.String(length=255), nullable=False),
        sa.Column("thread_id", sa.String(length=255), nullable=True),
        sa.Column("from_email", sa.String(length=320), nullable=True),
        sa.Column("from_name", sa.String(length=320), nullable=True),
        sa.Column("to_email", sa.String(length=320), nullable=True),
        sa.Column("subject", sa.String(length=998), nullable=True),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["account_id"], ["mail_accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_mail_messages_account_id"), "mail_messages", ["account_id"], unique=False
    )
    op.create_index(
        op.f("ix_mail_messages_from_email"), "mail_messages", ["from_email"], unique=False
    )
    op.create_index(
        op.f("ix_mail_messages_received_at"), "mail_messages", ["received_at"], unique=False
    )
    op.create_index(
        op.f("ix_mail_messages_thread_id"), "mail_messages", ["thread_id"], unique=False
    )
    op.create_index(
        "uq_mail_messages_account_provider_id",
        "mail_messages",
        ["account_id", "provider_message_id"],
        unique=True,
    )
    op.create_table(
        "mail_suggestions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("message_id", sa.UUID(), nullable=False),
        sa.Column("application_id", sa.UUID(), nullable=True),
        sa.Column(
            "suggested_status",
            postgresql.ENUM(name="application_status", create_type=False),
            nullable=True,
        ),
        sa.Column("confidence", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column(
            "source", sa.Enum("heuristic", "claude", name="suggestion_source"), nullable=False
        ),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column("signals", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "state",
            sa.Enum("pending", "accepted", "dismissed", name="suggestion_state"),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["message_id"], ["mail_messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id"),
    )
    op.create_index(
        op.f("ix_mail_suggestions_application_id"),
        "mail_suggestions",
        ["application_id"],
        unique=False,
    )
    op.create_index(op.f("ix_mail_suggestions_state"), "mail_suggestions", ["state"], unique=False)


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f("ix_mail_suggestions_state"), table_name="mail_suggestions")
    op.drop_index(op.f("ix_mail_suggestions_application_id"), table_name="mail_suggestions")
    op.drop_table("mail_suggestions")
    op.drop_index("uq_mail_messages_account_provider_id", table_name="mail_messages")
    op.drop_index(op.f("ix_mail_messages_thread_id"), table_name="mail_messages")
    op.drop_index(op.f("ix_mail_messages_received_at"), table_name="mail_messages")
    op.drop_index(op.f("ix_mail_messages_from_email"), table_name="mail_messages")
    op.drop_index(op.f("ix_mail_messages_account_id"), table_name="mail_messages")
    op.drop_table("mail_messages")
    op.drop_index("uq_mail_accounts_provider_address", table_name="mail_accounts")
    op.drop_table("mail_accounts")

    for enum_name in (
        "suggestion_state",
        "suggestion_source",
        "mail_account_status",
        "mail_provider_kind",
    ):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
    # `event_kind` keeps its `email` value: Postgres cannot drop one enum label,
    # and an unused label costs nothing.
