# app/config.py
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

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


class AuthSettings(BaseSettings):
    SSO_JWT_SECRET: str
    SSO_JWT_ALGORITHM: str = "HS256"
    SSO_BASE_URL: str = "http://localhost:8000/api"
    SSO_FRONTEND_URL: str = "http://localhost:5173"
    ACCESS_TOKEN_COOKIE_NAME: str = "access_token"
    CSRF_COOKIE_NAME: str = "csrf_token"
    CSRF_HEADER_NAME: str = "X-CSRF-Token"
    ENVIRONMENT: str = "development"

    model_config = _base_config

    @field_validator("SSO_JWT_SECRET")
    @classmethod
    def warn_short_secret(cls, value: str) -> str:
        if len(value) < 32:
            import logging

            logging.getLogger(__name__).warning(
                "SSO_JWT_SECRET is shorter than 32 characters — check it matches the SSO JWT_SECRET"
            )
        return value


class CorsSettings(BaseSettings):
    CORS_ALLOWED_ORIGINS: str = (
        "http://localhost:5173,http://localhost:5174,http://localhost:1576,"
        "http://localhost:1577,http://localhost:4173,http://localhost:4174,"
        "https://karanparmar.in,https://www.karanparmar.in"
    )

    model_config = _base_config

    @property
    def allowed_origins(self) -> list[str]:
        if not self.CORS_ALLOWED_ORIGINS:
            return []
        return [
            origin.strip()
            for origin in self.CORS_ALLOWED_ORIGINS.split(",")
            if origin.strip()
        ]


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
