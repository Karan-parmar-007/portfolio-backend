from typing import Annotated

from fastapi import Depends

from app.api.db_dependencies import GarageClientDep, PGSessionDep
from app.api.routes.contact_message.contact_service import ContactMessageService
from app.api.routes.education.education_service import EducationService
from app.api.routes.health.health_service import HealthService
from app.api.routes.media.media_service import MediaService
from app.api.routes.overview.overview_service import OverviewService
from app.api.routes.profile.profile_service import ProfileService
from app.api.routes.skill.skill_service import SkillService
from app.api.routes.social_media.social_media_service import SocialMediaService
from app.api.routes.work_experience.work_experience_service import WorkExperienceService


def get_health_service(
    session: PGSessionDep, garage: GarageClientDep
) -> HealthService:
    return HealthService(pg_session=session, garage_client=garage)


def get_media_service(
    session: PGSessionDep, garage: GarageClientDep
) -> MediaService:
    return MediaService(pg_session=session, garage_client=garage)


def get_profile_service(
    session: PGSessionDep, garage: GarageClientDep
) -> ProfileService:
    return ProfileService(pg_session=session, garage_client=garage)


def get_education_service(session: PGSessionDep) -> EducationService:
    return EducationService(pg_session=session)


def get_work_experience_service(session: PGSessionDep) -> WorkExperienceService:
    return WorkExperienceService(pg_session=session)


def get_social_media_service(session: PGSessionDep) -> SocialMediaService:
    return SocialMediaService(pg_session=session)


def get_skill_service(
    session: PGSessionDep, garage: GarageClientDep
) -> SkillService:
    return SkillService(pg_session=session, garage_client=garage)


def get_overview_service(
    session: PGSessionDep, garage: GarageClientDep
) -> OverviewService:
    return OverviewService(pg_session=session, garage_client=garage)


def get_contact_message_service(session: PGSessionDep) -> ContactMessageService:
    return ContactMessageService(pg_session=session)


type HealthServiceDep = Annotated[HealthService, Depends(get_health_service)]
type MediaServiceDep = Annotated[MediaService, Depends(get_media_service)]
type ProfileServiceDep = Annotated[ProfileService, Depends(get_profile_service)]
type EducationServiceDep = Annotated[EducationService, Depends(get_education_service)]
type WorkExperienceServiceDep = Annotated[
    WorkExperienceService, Depends(get_work_experience_service)
]
type SocialMediaServiceDep = Annotated[
    SocialMediaService, Depends(get_social_media_service)
]
type SkillServiceDep = Annotated[SkillService, Depends(get_skill_service)]
type OverviewServiceDep = Annotated[OverviewService, Depends(get_overview_service)]
type ContactMessageServiceDep = Annotated[
    ContactMessageService, Depends(get_contact_message_service)
]
