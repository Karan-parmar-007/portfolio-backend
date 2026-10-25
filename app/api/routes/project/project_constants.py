# app/api/routes/project/project_constants.py
from enum import Enum


class ProjectStatus(str, Enum):
    LIVE = "live"
    OFFLINE = "offline"
    ARCHIVED = "archived"


# Featured projects (any status, archived included) always sort first.
MAX_FEATURED_PROJECTS = 12
# Non-featured projects shown on the home page under the featured ones.
OVERVIEW_OTHER_PROJECTS = 6

MAX_TECH_STACK_ITEMS = 30
MAX_TAGS_PER_PROJECT = 20
MAX_LABEL_LENGTH = 50
MAX_URL_LENGTH = 500

PUBLIC_CACHE_CONTROL = "public, max-age=60"
