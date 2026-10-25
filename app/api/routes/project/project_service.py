from __future__ import annotations

import logging
from collections.abc import Sequence
from uuid import UUID

from fastapi import UploadFile
from sqlalchemy import Select, delete, func, literal, select, text, true
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.routes.media.media_schemas import media_asset_to_ref
from app.api.routes.media.media_service import MediaService
from app.api.routes.project.model import Project, ProjectTag, ProjectTagLink
from app.api.routes.project.project_constants import (
    MAX_FEATURED_PROJECTS,
    OVERVIEW_OTHER_PROJECTS,
    ProjectStatus,
)
from app.api.routes.project.project_schemas import (
    FacetCount,
    ProjectCreateRequest,
    ProjectDetail,
    ProjectFacetsResponse,
    ProjectPage,
    ProjectSummary,
    ProjectTagResponse,
    ProjectUpdateRequest,
)
from app.api.schemas.pagination import PaginationParams
from app.core.constants import MediaKind
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.html_sanitize import sanitize_project_html
from app.core.slug import unique_slug

logger = logging.getLogger(__name__)

# Serialises "turn featured on" so two admins cannot both take the last slot.
_FEATURED_LOCK_SQL = text("SELECT pg_advisory_xact_lock(hashtext('portfolio:projects:featured'))")

_ORDER = (Project.is_featured.desc(), Project.sequence.asc(), Project.name.asc())


def _like_pattern(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _with_relations(stmt: Select) -> Select:
    return stmt.options(selectinload(Project.tags), selectinload(Project.cover))


def _summary(p: Project, *, public: bool) -> ProjectSummary:
    return ProjectSummary(**_summary_fields(p, public=public))


def _summary_fields(p: Project, *, public: bool) -> dict:
    status = ProjectStatus(p.status)
    # "Try it now" only makes sense while the project actually runs.
    try_url = p.try_url if not public or status is ProjectStatus.LIVE else None
    return {
        "id": p.id,
        "name": p.name,
        "slug": p.slug,
        "short_description": p.short_description,
        "status": status,
        "is_featured": p.is_featured,
        "sequence": p.sequence,
        "github_url": p.github_url,
        "try_url": try_url,
        "cover": media_asset_to_ref(p.cover),
        "tech_stack": list(p.tech_stack or []),
        "tags": [t.name for t in p.tags],
    }


def _detail(p: Project, *, public: bool) -> ProjectDetail:
    return ProjectDetail(
        **_summary_fields(p, public=public),
        long_description=p.long_description,
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


class ProjectService:
    def __init__(self, pg_session: AsyncSession, garage_client: object) -> None:
        self.pg_session = pg_session
        self.media = MediaService(pg_session=pg_session, garage_client=garage_client)

    # ---------- loading ----------

    async def _load(self, project_id: UUID) -> Project:
        row = (
            await self.pg_session.execute(
                _with_relations(select(Project).where(Project.id == project_id))
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("Project not found")
        return row

    # ---------- public ----------

    async def list_public(
        self,
        *,
        q: str | None,
        statuses: Sequence[ProjectStatus],
        skill: str | None,
        tag: str | None,
        pagination: PaginationParams,
    ) -> ProjectPage:
        filters = []
        term = (q or "").strip()
        if term:
            filters.append(Project.search_text.ilike(_like_pattern(term), escape="\\"))
        if statuses:
            filters.append(Project.status.in_([s.value for s in statuses]))
        if skill:
            filters.append(Project.tech_stack.contains([skill]))
        if tag:
            filters.append(
                Project.id.in_(
                    select(ProjectTagLink.project_id)
                    .join(ProjectTag, ProjectTag.id == ProjectTagLink.tag_id)
                    .where(func.lower(ProjectTag.name) == tag.strip().lower())
                )
            )

        # One round trip for the page and the total (window count).
        stmt = (
            _with_relations(
                select(Project, func.count().over().label("total")).where(*filters)
            )
            .order_by(*_ORDER)
            .limit(pagination.page_size)
            .offset(pagination.offset)
        )
        rows = (await self.pg_session.execute(stmt)).all()
        if rows:
            total = rows[0].total
        elif pagination.page == 1:
            total = 0
        else:
            total = (
                await self.pg_session.execute(
                    select(func.count()).select_from(Project).where(*filters)
                )
            ).scalar_one()
        items = [_summary(row.Project, public=True) for row in rows]
        return ProjectPage.from_page(items, total=total, pagination=pagination)

    async def get_public(self, slug: str) -> ProjectDetail:
        row = (
            await self.pg_session.execute(
                _with_relations(select(Project).where(Project.slug == slug))
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("Project not found")
        return _detail(row, public=True)

    async def facets(self) -> ProjectFacetsResponse:
        status_rows = (
            await self.pg_session.execute(
                select(Project.status, func.count()).group_by(Project.status)
            )
        ).all()
        by_status = {status: count for status, count in status_rows}
        statuses = [
            FacetCount(value=s.value, count=by_status.get(s.value, 0)) for s in ProjectStatus
        ]

        skill = func.jsonb_array_elements_text(Project.tech_stack).table_valued("value")
        skill_count = func.count().label("n")
        skill_rows = (
            await self.pg_session.execute(
                select(skill.c.value, skill_count)
                .select_from(Project)
                .join(skill, true())
                .group_by(skill.c.value)
                .order_by(skill_count.desc(), skill.c.value.asc())
            )
        ).all()

        tag_count = func.count(ProjectTagLink.project_id).label("n")
        tag_rows = (
            await self.pg_session.execute(
                select(ProjectTag.name, tag_count)
                .join(ProjectTagLink, ProjectTagLink.tag_id == ProjectTag.id)
                .group_by(ProjectTag.name)
                .order_by(tag_count.desc(), ProjectTag.name.asc())
            )
        ).all()

        return ProjectFacetsResponse(
            total=sum(by_status.values()),
            statuses=statuses,
            skills=[FacetCount(value=v, count=n) for v, n in skill_rows],
            tags=[FacetCount(value=v, count=n) for v, n in tag_rows],
        )

    async def overview_lists(
        self,
    ) -> tuple[list[ProjectSummary], list[ProjectSummary], int]:
        """Featured (up to the cap), the first non-featured few, and the total."""
        featured_rows = (
            await self.pg_session.execute(
                _with_relations(select(Project).where(Project.is_featured.is_(True)))
                .order_by(*_ORDER)
                .limit(MAX_FEATURED_PROJECTS)
            )
        ).scalars().all()
        other_rows = (
            await self.pg_session.execute(
                _with_relations(select(Project).where(Project.is_featured.is_(False)))
                .order_by(*_ORDER)
                .limit(OVERVIEW_OTHER_PROJECTS)
            )
        ).scalars().all()
        total = (
            await self.pg_session.execute(select(func.count()).select_from(Project))
        ).scalar_one()
        return (
            [_summary(p, public=True) for p in featured_rows],
            [_summary(p, public=True) for p in other_rows],
            total,
        )

    # ---------- admin ----------

    async def admin_list(self, *, q: str | None) -> list[ProjectSummary]:
        stmt = _with_relations(select(Project)).order_by(*_ORDER)
        term = (q or "").strip()
        if term:
            stmt = stmt.where(Project.search_text.ilike(_like_pattern(term), escape="\\"))
        rows = (await self.pg_session.execute(stmt)).scalars().all()
        return [_summary(p, public=False) for p in rows]

    async def admin_get(self, project_id: UUID) -> ProjectDetail:
        return _detail(await self._load(project_id), public=False)

    async def _assert_name_free(self, name: str, *, exclude_id: UUID | None = None) -> None:
        stmt = select(Project.id).where(func.lower(Project.name) == name.lower())
        if exclude_id is not None:
            stmt = stmt.where(Project.id != exclude_id)
        if (await self.pg_session.execute(stmt)).first() is not None:
            raise ConflictError("A project with this name already exists")

    async def _assert_featured_slot(self, *, exclude_id: UUID | None = None) -> None:
        await self.pg_session.execute(_FEATURED_LOCK_SQL)
        stmt = select(func.count()).select_from(Project).where(Project.is_featured.is_(True))
        if exclude_id is not None:
            stmt = stmt.where(Project.id != exclude_id)
        if (await self.pg_session.execute(stmt)).scalar_one() >= MAX_FEATURED_PROJECTS:
            raise ConflictError(
                f"At most {MAX_FEATURED_PROJECTS} projects can be featured. "
                "Unfeature one first."
            )

    async def _resolve_tags(self, names: list[str]) -> list[ProjectTag]:
        if not names:
            return []
        lowered = [n.lower() for n in names]
        existing = (
            await self.pg_session.execute(
                select(ProjectTag).where(func.lower(ProjectTag.name).in_(lowered))
            )
        ).scalars().all()
        by_lower = {t.name.lower(): t for t in existing}
        result: list[ProjectTag] = []
        for name in names:
            tag = by_lower.get(name.lower())
            if tag is None:
                tag = ProjectTag(name=name)
                self.pg_session.add(tag)
                by_lower[name.lower()] = tag
            result.append(tag)
        return result

    async def _release_cover(self, media_id: UUID | None) -> None:
        """Delete a cover once no project uses it (identical uploads share a row)."""
        if media_id is None:
            return
        in_use = (
            await self.pg_session.execute(
                select(Project.id).where(Project.cover_media_id == media_id).limit(1)
            )
        ).first()
        if in_use is None:
            await self.media.delete(media_id)

    async def _commit(self) -> None:
        try:
            await self.pg_session.commit()
        except IntegrityError as exc:
            await self.pg_session.rollback()
            raise ConflictError("A project with this name or slug already exists") from exc

    async def create(self, data: ProjectCreateRequest) -> ProjectDetail:
        await self._assert_name_free(data.name)
        if data.is_featured:
            await self._assert_featured_slot()
        max_seq = (
            await self.pg_session.execute(select(func.max(Project.sequence)))
        ).scalar_one_or_none()
        project = Project(
            name=data.name,
            slug=await unique_slug(self.pg_session, Project, data.name),
            short_description=data.short_description,
            long_description=sanitize_project_html(data.long_description),
            status=data.status.value,
            is_featured=data.is_featured,
            sequence=(max_seq or 0) + 1,
            github_url=data.github_url,
            try_url=data.try_url,
            tech_stack=data.tech_stack,
        )
        project.tags = await self._resolve_tags(data.tags)
        self.pg_session.add(project)
        await self._commit()
        return await self.admin_get(project.id)

    async def update(self, project_id: UUID, data: ProjectUpdateRequest) -> ProjectDetail:
        project = await self._load(project_id)
        payload = data.model_dump(exclude_unset=True)

        name = payload.pop("name", None)
        if name is not None and name != project.name:
            await self._assert_name_free(name, exclude_id=project_id)
            project.name = name
            project.slug = await unique_slug(
                self.pg_session, Project, name, exclude_id=project_id
            )
        if payload.get("is_featured") is True and not project.is_featured:
            await self._assert_featured_slot(exclude_id=project_id)
        if "long_description" in payload:
            payload["long_description"] = sanitize_project_html(
                payload["long_description"]
            )
        if "status" in payload and payload["status"] is not None:
            payload["status"] = payload["status"].value
        if "tags" in payload:
            project.tags = await self._resolve_tags(payload.pop("tags") or [])
        for key, value in payload.items():
            if value is None and key not in {"github_url", "try_url"}:
                continue  # explicit null only clears the optional links
            setattr(project, key, value)
        await self._commit()
        return await self.admin_get(project_id)

    async def set_featured(self, project_id: UUID, is_featured: bool) -> ProjectDetail:
        project = await self._load(project_id)
        if is_featured and not project.is_featured:
            await self._assert_featured_slot(exclude_id=project_id)
        project.is_featured = is_featured
        await self._commit()
        return await self.admin_get(project_id)

    async def set_status(self, project_id: UUID, status: ProjectStatus) -> ProjectDetail:
        project = await self._load(project_id)
        project.status = status.value
        await self._commit()
        return await self.admin_get(project_id)

    async def reorder(self, ids: list[UUID]) -> list[ProjectSummary]:
        rows = (await self.pg_session.execute(select(Project))).scalars().all()
        by_id = {r.id: r for r in rows}
        if len(ids) != len(set(ids)) or set(ids) != set(by_id):
            raise ValidationError("Reorder must include every existing id exactly once")
        for index, item_id in enumerate(ids):
            by_id[item_id].sequence = index + 1
        await self._commit()
        return await self.admin_list(q=None)

    async def delete(self, project_id: UUID) -> None:
        project = await self._load(project_id)
        cover_id = project.cover_media_id
        await self.pg_session.delete(project)
        await self._commit()
        await self._release_cover(cover_id)

    async def set_cover(self, project_id: UUID, file: UploadFile) -> ProjectDetail:
        project = await self._load(project_id)
        old_id = project.cover_media_id
        asset = await self.media.store(file, MediaKind.PROJECT_COVER)
        project.cover_media_id = asset.id
        try:
            await self.pg_session.commit()
        except Exception:
            await self.pg_session.rollback()
            if asset.id != old_id:
                await self._release_cover(asset.id)
            raise
        if old_id != asset.id:
            await self._release_cover(old_id)
        return await self.admin_get(project_id)

    async def delete_cover(self, project_id: UUID) -> ProjectDetail:
        project = await self._load(project_id)
        old_id = project.cover_media_id
        project.cover_media_id = None
        await self.pg_session.commit()
        await self._release_cover(old_id)
        return await self.admin_get(project_id)

    # ---------- tags ----------

    async def list_tags(self) -> list[ProjectTagResponse]:
        count = func.count(ProjectTagLink.project_id)
        rows = (
            await self.pg_session.execute(
                select(ProjectTag.id, ProjectTag.name, count)
                .outerjoin(ProjectTagLink, ProjectTagLink.tag_id == ProjectTag.id)
                .group_by(ProjectTag.id, ProjectTag.name)
                .order_by(ProjectTag.name.asc())
            )
        ).all()
        return [ProjectTagResponse(id=i, name=n, project_count=c) for i, n, c in rows]

    async def create_tag(self, name: str) -> ProjectTagResponse:
        clash = (
            await self.pg_session.execute(
                select(ProjectTag.id).where(func.lower(ProjectTag.name) == name.lower())
            )
        ).first()
        if clash is not None:
            raise ConflictError("Tag already exists")
        tag = ProjectTag(name=name)
        self.pg_session.add(tag)
        try:
            await self.pg_session.commit()
        except IntegrityError as exc:
            await self.pg_session.rollback()
            raise ConflictError("Tag already exists") from exc
        return ProjectTagResponse(id=tag.id, name=tag.name, project_count=0)

    async def delete_tag(self, tag_id: UUID) -> None:
        result = await self.pg_session.execute(
            delete(ProjectTag).where(ProjectTag.id == tag_id).returning(literal(1))
        )
        if result.first() is None:
            raise NotFoundError("Tag not found")
        await self.pg_session.commit()

