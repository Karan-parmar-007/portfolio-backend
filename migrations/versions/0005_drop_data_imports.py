"""Drop data_imports: the one-off all_projects import is done and removed.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-25 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS data_imports")


def downgrade() -> None:
    op.create_table(
        "data_imports",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column(
            "done_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint("key"),
    )
