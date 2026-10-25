# app/config.py
from urllib.parse import urlsplit

from pydantic_settings import BaseSettings, SettingsConfigDict

from karan_sso import SsoSettings

_base_config = SettingsConfigDict(
    env_file=".env",
    env_file_encoding="utf-8",
    env_ignore_empty=True,
    extra="ignore",
)


class DatabaseSettings(BaseSettings):
    POSTGRES_SERVER: str
    POSTGRES_PORT: int
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    POSTGRES_ECHO: bool = False

    GARAGE_ENDPOINT_URL: str
    GARAGE_ACCESS_KEY: str
    GARAGE_SECRET_KEY: str
    GARAGE_BUCKET_NAME: str
    GARAGE_REGION_NAME: str

    model_config = _base_config

    @property
    def POSTGRES_URL(self) -> str:
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


class AuthSettings(SsoSettings):
    """SSO SDK settings (karan_sso) plus this app's defaults.

    Read by `karan_sso` for token verification, live role checks and CSRF:
    SSO_BASE_URL, SSO_ISSUER, SSO_AUDIENCE, SSO_REQUIRE_AUDIENCE,
    SSO_JWT_SECRET (legacy HS256, rollout only), SSO_APP_ID, cookie names.
    """

    SSO_APP_ID: str = "portfolio"
    ENVIRONMENT: str = "development"

    model_config = _base_config

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.strip().lower() == "production"


_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "::1"})


class CorsSettings(BaseSettings):
    CORS_ALLOWED_ORIGINS: str = (
        "https://karanparmar.in,https://www.karanparmar.in,"
        "http://localhost:5173,http://localhost:5174,http://localhost:1576,"
        "http://localhost:1577,http://localhost:4173,http://localhost:4174"
    )

    model_config = _base_config

    def allowed_origins(self, *, production: bool) -> list[str]:
        """Explicit origins; localhost is dropped in production."""
        origins = [
            origin.strip().rstrip("/")
            for origin in self.CORS_ALLOWED_ORIGINS.split(",")
            if origin.strip()
        ]
        if production:
            origins = [o for o in origins if urlsplit(o).hostname not in _LOCAL_HOSTS]
        return origins


class MediaSettings(BaseSettings):
    MEDIA_MAX_IMAGE_BYTES: int = 5_242_880
    MEDIA_MAX_DOCUMENT_BYTES: int = 10_485_760
    MEDIA_ALLOWED_IMAGE_TYPES: str = (
        "image/png,image/jpeg,image/webp,image/svg+xml,image/avif"
    )
    MEDIA_ALLOWED_DOCUMENT_TYPES: str = "application/pdf"
    MEDIA_CACHE_MAX_AGE_SECONDS: int = 31_536_000

    model_config = _base_config

    @property
    def allowed_image_types(self) -> set[str]:
        return {t.strip() for t in self.MEDIA_ALLOWED_IMAGE_TYPES.split(",") if t.strip()}

    @property
    def allowed_document_types(self) -> set[str]:
        return {
            t.strip() for t in self.MEDIA_ALLOWED_DOCUMENT_TYPES.split(",") if t.strip()
        }


class LegacySettings(BaseSettings):
    LEGACY_POSTGRES_URL: str = ""
    LEGACY_MONGO_URI: str = ""
    LEGACY_MONGO_DB_NAME: str = "my_website"

    model_config = _base_config


db_settings = DatabaseSettings()  # type: ignore[call-arg]
auth_settings = AuthSettings()  # type: ignore[call-arg]
cors_settings = CorsSettings()  # type: ignore[call-arg]
media_settings = MediaSettings()  # type: ignore[call-arg]
legacy_settings = LegacySettings()  # type: ignore[call-arg]
