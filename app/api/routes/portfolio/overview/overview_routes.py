from fastapi import APIRouter

from app.api.dependencies import OverviewServiceDep
from app.api.routes.portfolio.overview.overview_schemas import OverviewResponse

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("/overview", response_model=OverviewResponse)
async def get_overview(service: OverviewServiceDep) -> OverviewResponse:
    return await service.get_overview()
