"""Search extensions, triggers, and GIN indexes.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-26 00:01:00.000000
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent;")

    op.execute("""
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
    """)

    op.execute("""
        CREATE TRIGGER trg_projects_search_vector
        BEFORE INSERT OR UPDATE ON projects
        FOR EACH ROW
        EXECUTE FUNCTION projects_search_vector_update();
    """)

    op.execute("""
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
    """)

    op.execute("""
        CREATE TRIGGER trg_project_skill_search_vector
        AFTER INSERT OR DELETE ON project_skills
        FOR EACH ROW EXECUTE FUNCTION project_skill_search_vector_update();
    """)

    op.execute(
        "CREATE INDEX idx_projects_search_vector ON projects USING GIN (search_vector);"
    )
    op.execute(
        "CREATE INDEX idx_projects_name_trgm ON projects USING GIN (name gin_trgm_ops);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_projects_name_trgm;")
    op.execute("DROP INDEX IF EXISTS idx_projects_search_vector;")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_project_skill_search_vector ON project_skills;"
    )
    op.execute("DROP FUNCTION IF EXISTS project_skill_search_vector_update();")
    op.execute("DROP TRIGGER IF EXISTS trg_projects_search_vector ON projects;")
    op.execute("DROP FUNCTION IF EXISTS projects_search_vector_update();")
    # Extensions intentionally left installed — dropping may break other DBs/apps.
