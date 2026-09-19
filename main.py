# main.py
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.main_router import main_router
from app.api.middlewares.csrf import CSRFMiddleware
from app.api.routes.auth import auth_routes
from app.config import cors_settings
from app.core.errors import register_exception_handlers
from app.db.garage_session import GarageSession
from app.db.postgress_session import PostgresSession

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    postgres_session = PostgresSession()
    garage_session = GarageSession()

    await postgres_session.verify_connection()

    app.state.postgres_session = postgres_session
    app.state.garage_session = garage_session

    yield

    await postgres_session.dispose()


app = FastAPI(title="Portfolio API", lifespan=lifespan)
register_exception_handlers(app)
# CSRF first, CORS last so CORS wraps CSRF and preflights never hit CSRF.
app.add_middleware(CSRFMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(main_router)
# Local-dev cookie path: refresh_token is scoped to /api/auth
app.include_router(auth_routes.router, prefix="/api")
