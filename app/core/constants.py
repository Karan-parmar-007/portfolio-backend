# app/core/constants.py
from enum import Enum


class MediaKind(str, Enum):
    PROFILE_IMAGE = "profile_image"
    RESUME = "resume"
    SKILL_ICON = "skill_icon"
    PROJECT_COVER = "project_cover"


class ProjectSort(str, Enum):
    SEQUENCE = "sequence"
    NEWEST = "newest"
    OLDEST = "oldest"
    NAME = "name"
    RELEVANCE = "relevance"


SOCIAL_PLATFORMS = frozenset(
    {
        "github",
        "linkedin",
        "instagram",
        "twitter",
        "x",
        "youtube",
        "codepen",
        "stackoverflow",
        "medium",
        "dribbble",
        "email",
    }
)

MEDIA_KIND_PREFIX: dict[MediaKind, str] = {
    MediaKind.PROFILE_IMAGE: "portfolio/profile",
    MediaKind.RESUME: "portfolio/resume",
    MediaKind.SKILL_ICON: "portfolio/skills",
    MediaKind.PROJECT_COVER: "portfolio/projects",
}
