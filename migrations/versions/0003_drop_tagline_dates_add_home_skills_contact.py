"""Drop hero tagline and project dates; home skill flags; contact inbox.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-29 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("profile_info", "hero_tagline")
    op.drop_column("projects", "started_at")
    op.drop_column("projects", "completed_at")

    op.add_column(
        "skill_categories",
        sa.Column(
            "show_on_home",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.execute(
        """
        UPDATE skill_categories
        SET show_on_home = true
        WHERE id IN (
            SELECT id FROM skill_categories
            ORDER BY sequence ASC
            LIMIT 3
        )
        """
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_projects_short_desc_trgm "
        "ON projects USING GIN (short_description gin_trgm_ops);"
    )

    op.create_table(
        "contact_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("phone", sa.String(length=30), nullable=True),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "is_read",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_contact_messages_created_at",
        "contact_messages",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_contact_messages_created_at", table_name="contact_messages")
    op.drop_table("contact_messages")
    op.execute("DROP INDEX IF EXISTS idx_projects_short_desc_trgm;")
    op.drop_column("skill_categories", "show_on_home")
    op.add_column(
        "projects",
        sa.Column("completed_at", sa.Date(), nullable=True),
    )
    op.add_column(
        "projects",
        sa.Column("started_at", sa.Date(), nullable=True),
    )
    op.add_column(
        "profile_info",
        sa.Column("hero_tagline", sa.String(length=500), nullable=True),
    )
