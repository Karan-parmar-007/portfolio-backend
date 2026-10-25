from fastapi import APIRouter

from app.api.routes.health import health_routes
from app.api.routes.media import media_routes
from app.api.routes.portfolio.contact_message import (
    admin_contact_routes,
    contact_routes,
)
from app.api.routes.portfolio.education import admin_education_routes, education_routes
from app.api.routes.portfolio.overview import overview_routes
from app.api.routes.portfolio.profile import admin_profile_routes, profile_routes
from app.api.routes.portfolio.social_media import (
    admin_social_media_routes,
    social_media_routes,
)
from app.api.routes.portfolio.work_experience import (
    admin_work_experience_routes,
    work_experience_routes,
)
from app.api.routes.project import admin_project_routes, project_routes
from app.api.routes.skill import admin_skill_routes, skill_routes

main_router = APIRouter(prefix="/api/portfolio")

# Public
main_router.include_router(health_routes.router)
main_router.include_router(media_routes.router)
main_router.include_router(overview_routes.router)
main_router.include_router(profile_routes.router)
main_router.include_router(education_routes.router)
main_router.include_router(work_experience_routes.router)
main_router.include_router(social_media_routes.router)
main_router.include_router(contact_routes.router)
main_router.include_router(project_routes.router)
main_router.include_router(skill_routes.router)

# Admin
main_router.include_router(admin_profile_routes.router)
main_router.include_router(admin_education_routes.router)
main_router.include_router(admin_work_experience_routes.router)
main_router.include_router(admin_social_media_routes.router)
main_router.include_router(admin_contact_routes.router)
main_router.include_router(admin_project_routes.router)
main_router.include_router(admin_skill_routes.router)
