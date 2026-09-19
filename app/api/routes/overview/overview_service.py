from __future__ import annotations

from app.api.routes.education.education_service import EducationService
from app.api.routes.overview.overview_schemas import OverviewResponse
from app.api.routes.profile.profile_service import ProfileService
from app.api.routes.social_media.social_media_service import SocialMediaService
from app.api.routes.work_experience.work_experience_service import WorkExperienceService
from app.core.errors import NotFoundError
from sqlalchemy.ext.asyncio import AsyncSession


class OverviewService:
    def __init__(self, pg_session: AsyncSession, garage_client: object) -> None:
        self.pg_session = pg_session
        self.garage_client = garage_client

    async def get_overview(self) -> OverviewResponse:
        profile_svc = ProfileService(self.pg_session, self.garage_client)
        education_svc = EducationService(self.pg_session)
        work_svc = WorkExperienceService(self.pg_session)
        social_svc = SocialMediaService(self.pg_session)

        try:
            profile = await profile_svc.get_public()
        except NotFoundError:
            profile = None

        education = await education_svc.list_all()
        work_experience = await work_svc.list_all()
        social_media = await social_svc.list_all(in_rail=True)

        return OverviewResponse(
            profile=profile,
            education=education,
            work_experience=work_experience,
            skill_categories=[],
            about_skills=[],
            social_media=social_media,
        )
