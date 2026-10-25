"""Projects module: projects, project_tags, project_tag_links, data_imports.

The 0001 `projects` / `project_skills` / `access_levels` tables were never
used by this API. They are renamed to `legacy_*` (indexes too, so their
names are free again) instead of dropped, and their search triggers go away.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-25 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LEGACY_TABLES = ("projects", "project_skills", "access_levels")

# Same expression as Project.search_text; jsonb::text keeps it immutable.
_SEARCH_TEXT = (
    "name || ' ' || short_description || ' ' || (tech_stack)::text"
)


def _rename_tables(old_prefix: str, new_prefix: str) -> None:
    """Rename each legacy table and every index on it (pkey/unique included)."""
    for table in _LEGACY_TABLES:
        old = f"{old_prefix}{table}"
        new = f"{new_prefix}{table}"
        op.execute(
            f"""
            DO $$
            DECLARE idx record;
            BEGIN
                IF to_regclass('public.{old}') IS NOT NULL
                   AND to_regclass('public.{new}') IS NULL THEN
                    FOR idx IN
                        SELECT indexname FROM pg_indexes
                        WHERE schemaname = 'public' AND tablename = '{old}'
                    LOOP
                        EXECUTE format(
                            'ALTER INDEX %I RENAME TO %I',
                            idx.indexname,
                            '{new_prefix}' || substr(idx.indexname, {len(old_prefix) + 1})
                        );
                    END LOOP;
                    EXECUTE 'ALTER TABLE {old} RENAME TO {new}';
                END IF;
            END $$;
            """
        )


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")

    # Legacy search triggers reference the old table names; drop them first.
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.projects') IS NOT NULL THEN
                DROP TRIGGER IF EXISTS trg_projects_search_vector ON projects;
            END IF;
            IF to_regclass('public.project_skills') IS NOT NULL THEN
                DROP TRIGGER IF EXISTS trg_project_skill_search_vector ON project_skills;
            END IF;
        END $$;
        """
    )
    op.execute("DROP FUNCTION IF EXISTS project_skill_search_vector_update();")
    op.execute("DROP FUNCTION IF EXISTS projects_search_vector_update();")
    _rename_tables("", "legacy_")

    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("slug", sa.String(length=180), nullable=False),
        sa.Column("short_description", sa.Text(), nullable=False),
        sa.Column("long_description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "is_featured", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("sequence", sa.Integer(), server_default="0", nullable=False),
        sa.Column("github_url", sa.String(length=500), nullable=True),
        sa.Column("try_url", sa.String(length=500), nullable=True),
        sa.Column("cover_media_id", sa.Uuid(), nullable=True),
        sa.Column(
            "tech_stack",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "search_text",
            sa.Text(),
            sa.Computed(_SEARCH_TEXT, persisted=True),
            nullable=True,
        ),
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
        sa.ForeignKeyConstraint(
            ["cover_media_id"], ["media_assets.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        sa.UniqueConstraint("slug"),
        sa.CheckConstraint(
            "status IN ('live', 'offline', 'archived')", name="ck_projects_status"
        ),
    )
    # Default order everywhere: featured first, then the admin's sequence.
    op.execute(
        "CREATE INDEX ix_projects_order ON projects "
        "(is_featured DESC, sequence ASC, name ASC);"
    )
    op.create_index("ix_projects_status", "projects", ["status"])
    op.execute(
        "CREATE INDEX ix_projects_search_trgm ON projects "
        "USING GIN (search_text gin_trgm_ops);"
    )
    op.execute(
        "CREATE INDEX ix_projects_tech_stack ON projects "
        "USING GIN (tech_stack jsonb_path_ops);"
    )

    op.create_table(
        "project_tags",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "project_tag_links",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("tag_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["project_tags.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id", "tag_id"),
    )
    op.create_index("ix_project_tag_links_tag_id", "project_tag_links", ["tag_id"])

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


def downgrade() -> None:
    op.drop_table("data_imports")
    op.drop_index("ix_project_tag_links_tag_id", table_name="project_tag_links")
    op.drop_table("project_tag_links")
    op.drop_table("project_tags")
    op.execute("DROP INDEX IF EXISTS ix_projects_tech_stack;")
    op.execute("DROP INDEX IF EXISTS ix_projects_search_trgm;")
    op.execute("DROP INDEX IF EXISTS ix_projects_status;")
    op.execute("DROP INDEX IF EXISTS ix_projects_order;")
    op.drop_table("projects")

    _rename_tables("legacy_", "")

    # Restore the 0002 search triggers on the legacy tables.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION projects_search_vector_update() RETURNS trigger AS $$
        BEGIN
            NEW.search_vector :=
                setweight(to_tsvector('english', COALESCE(NEW.name, '')), 'A') ||
                setweight(to_tsvector('english', COALESCE(NEW.short_description, '')), 'B') ||
                setweight(to_tsvector('english', COALESCE(NEW.long_description, '')), 'C') ||
                setweight(to_tsvector('english', COALESCE(
                    (SELECT string_agg(s.name, ' ')
                     FROM project_skills ps JOIN skills s ON s.id = ps.skill_id
                     WHERE ps.project_id = NEW.id), ''
                )), 'B');
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_projects_search_vector
        BEFORE INSERT OR UPDATE ON projects
        FOR EACH ROW
        EXECUTE FUNCTION projects_search_vector_update();
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION project_skill_search_vector_update() RETURNS trigger AS $$
        DECLARE target_id UUID;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                target_id := OLD.project_id;
            ELSE
                target_id := NEW.project_id;
            END IF;
            UPDATE projects SET updated_at = now() WHERE id = target_id;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_project_skill_search_vector
        AFTER INSERT OR DELETE ON project_skills
        FOR EACH ROW EXECUTE FUNCTION project_skill_search_vector_update();
        """
    )
