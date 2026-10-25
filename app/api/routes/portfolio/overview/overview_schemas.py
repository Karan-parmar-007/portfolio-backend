from __future__ import annotations

from app.api.routes.portfolio.education.education_schemas import EducationResponse
from app.api.routes.portfolio.profile.profile_schemas import ProfileResponse
from app.api.routes.project.project_schemas import ProjectSummary
from app.api.routes.skill.skill_schemas import SkillCategoryResponse, SkillResponse
from app.api.routes.portfolio.social_media.social_media_schemas import SocialMediaResponse
from app.api.routes.portfolio.work_experience.work_experience_schemas import WorkExperienceResponse
from pydantic import BaseModel, Field


class OverviewResponse(BaseModel):
    profile: ProfileResponse | None = None
    education: list[EducationResponse] = Field(default_factory=list)
    work_experience: list[WorkExperienceResponse] = Field(default_factory=list)
    skill_categories: list[SkillCategoryResponse] = Field(default_factory=list)
    about_skills: list[SkillResponse] = Field(default_factory=list)
    social_media: list[SocialMediaResponse] = Field(default_factory=list)
    # Featured first (any status), then the first few others; full list at /projects.
    featured_projects: list[ProjectSummary] = Field(default_factory=list)
    projects: list[ProjectSummary] = Field(default_factory=list)
    project_count: int = 0
