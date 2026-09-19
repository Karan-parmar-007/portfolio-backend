import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status

from app.api.dependencies import HealthServiceDep
from app.api.routes.health.health_schemas import (
    HealthStatus,
    LivenessResponse,
    ReadinessResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["health"])


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@router.get(
    "/live",
    summary="Liveness probe",
    response_model=LivenessResponse,
)
async def liveness_check() -> LivenessResponse:
    return LivenessResponse(status=HealthStatus.HEALTHY, timestamp=_utc_now())


@router.get(
    "/ready",
    summary="Readiness probe",
    response_model=ReadinessResponse,
    responses={503: {"description": "One or more dependencies are unavailable"}},
)
async def readiness_check(health_service: HealthServiceDep) -> ReadinessResponse:
    try:
        pg_ok, garage_ok = await asyncio.gather(
            health_service.check_postgres(),
            health_service.check_garage(),
        )
    except Exception:
        logger.exception("readiness check failed unexpectedly")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Readiness check failed",
        )

    checks = {
        "postgres": "ok" if pg_ok else "fail",
        "garage": "ok" if garage_ok else "fail",
    }
    overall = "ready" if pg_ok and garage_ok else "not_ready"
    response = ReadinessResponse(
        status=overall,
        checks=checks,
        timestamp=_utc_now(),
    )

    if overall != "ready":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=response.model_dump(mode="json"),
        )

    return response
