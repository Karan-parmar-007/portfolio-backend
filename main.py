# main.py
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from karan_sso.fastapi import CSRFMiddleware, configure

from app.api.main_router import main_router
from app.config import auth_settings, cors_settings
from app.core.errors import register_exception_handlers
from app.db.garage_session import GarageSession
from app.db.postgress_session import PostgresSession
from bootstrap import run_bootstrap

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# One SSO SDK instance for every auth dependency (SSO_APP_ID=portfolio).
configure(auth_settings)


@asynccontextmanager
async def lifespan(app: FastAPI):
    postgres_session = PostgresSession()
    garage_session = GarageSession()

    await postgres_session.verify_connection()

    app.state.postgres_session = postgres_session
    app.state.garage_session = garage_session

    try:
        await run_bootstrap(postgres_session._sessionmaker, garage_session)
    except Exception:
        logger.exception("Portfolio bootstrap failed")

    yield

    await postgres_session.dispose()


_docs_enabled = not auth_settings.is_production

app = FastAPI(
    title="Portfolio API",
    lifespan=lifespan,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)
register_exception_handlers(app)
# CSRF first, CORS last so CORS wraps CSRF and preflights never hit CSRF.
# CSRF applies only to cookie-authenticated mutations; anonymous POSTs
# (e.g. the public contact form) carry no session cookie and pass through.
app.add_middleware(
    CSRFMiddleware,
    exempt_prefixes=("/health", "/api/portfolio/health"),
    settings=auth_settings,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_settings.allowed_origins(production=auth_settings.is_production),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", auth_settings.CSRF_HEADER_NAME],
)
app.include_router(main_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
