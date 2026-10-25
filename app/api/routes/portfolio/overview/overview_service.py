from __future__ import annotations

from app.api.routes.portfolio.education.education_service import EducationService
from app.api.routes.portfolio.overview.overview_schemas import OverviewResponse
from app.api.routes.portfolio.profile.profile_service import ProfileService
from app.api.routes.project.project_service import ProjectService
from app.api.routes.skill.skill_service import SkillService
from app.api.routes.portfolio.social_media.social_media_service import SocialMediaService
from app.api.routes.portfolio.work_experience.work_experience_service import WorkExperienceService
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
        skill_svc = SkillService(self.pg_session, self.garage_client)
        project_svc = ProjectService(self.pg_session, self.garage_client)

        try:
            profile = await profile_svc.get_public()
        except NotFoundError:
            profile = None

        education = await education_svc.list_all()
        work_experience = await work_svc.list_all()
        social_media = await social_svc.list_all(in_rail=True)
        skill_categories = await skill_svc.list_categories(on_home=True)
        about_skills = await skill_svc.list_skills(in_about=True)
        featured, others, project_count = await project_svc.overview_lists()

        return OverviewResponse(
            profile=profile,
            education=education,
            work_experience=work_experience,
            skill_categories=skill_categories,
            about_skills=about_skills,
            social_media=social_media,
            featured_projects=featured,
            projects=others,
            project_count=project_count,
        )
