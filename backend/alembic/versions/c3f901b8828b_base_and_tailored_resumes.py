"""base and tailored resumes

Splits the single `resume` document kind into a base resume (the master, one of
which is marked `is_base`) and tailored resumes written from it.

Alembic does not detect Postgres enum value changes, so the type swap below is
written by hand: autogenerate saw only the new columns.

Revision ID: c3f901b8828b
Revises: bdae58f29f2e
"""

import sqlalchemy as sa

from alembic import op

revision = 'c3f901b8828b'
down_revision = 'bdae58f29f2e'
branch_labels = None
depends_on = None

NEW_KINDS = (
    "base_resume",
    "tailored_resume",
    "cover_letter",
    "portfolio",
    "offer_letter",
    "other",
)
OLD_KINDS = ("resume", "cover_letter", "portfolio", "offer_letter", "other")


def _swap_enum(new_values, mapping_sql, old_name="document_kind"):
    """Replace the document_kind enum, remapping existing rows as we go."""
    values = ", ".join(f"'{v}'" for v in new_values)
    op.execute(f"ALTER TYPE {old_name} RENAME TO {old_name}_old")
    op.execute(f"CREATE TYPE {old_name} AS ENUM ({values})")
    op.execute("ALTER TABLE documents ALTER COLUMN kind DROP DEFAULT")
    op.execute(
        f"ALTER TABLE documents ALTER COLUMN kind TYPE {old_name} "
        f"USING ({mapping_sql})::{old_name}"
    )
    op.execute(f"DROP TYPE {old_name}_old")


def upgrade() -> None:
    # Existing resumes become base resumes.
    _swap_enum(
        NEW_KINDS,
        "CASE kind::text WHEN 'resume' THEN 'base_resume' ELSE kind::text END",
    )

    op.add_column(
        "documents",
        sa.Column("is_base", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # The default was only needed to backfill existing rows.
    op.alter_column("documents", "is_base", server_default=None)

    op.add_column("documents", sa.Column("derived_from_id", sa.UUID(), nullable=True))
    op.create_index(
        op.f("ix_documents_derived_from_id"), "documents", ["derived_from_id"], unique=False
    )
    op.create_foreign_key(
        "fk_documents_derived_from_id",
        "documents",
        "documents",
        ["derived_from_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "uq_documents_single_base",
        "documents",
        ["is_base"],
        unique=True,
        postgresql_where=sa.text("is_base"),
    )

    # Give the newest base resume the flag, so there is a designated base to
    # tailor from without the user having to go and pick one.
    op.execute(
        """
        UPDATE documents SET is_base = true
        WHERE id = (
            SELECT id FROM documents
            WHERE kind = 'base_resume'
            ORDER BY created_at DESC
            LIMIT 1
        )
        """
    )


def downgrade() -> None:
    op.drop_index("uq_documents_single_base", table_name="documents")
    op.drop_constraint("fk_documents_derived_from_id", "documents", type_="foreignkey")
    op.drop_index(op.f("ix_documents_derived_from_id"), table_name="documents")
    op.drop_column("documents", "derived_from_id")
    op.drop_column("documents", "is_base")

    # Both resume kinds collapse back to the single `resume` value.
    _swap_enum(
        OLD_KINDS,
        "CASE kind::text "
        "WHEN 'base_resume' THEN 'resume' "
        "WHEN 'tailored_resume' THEN 'resume' "
        "ELSE kind::text END",
    )
