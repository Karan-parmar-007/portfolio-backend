from fastapi import APIRouter, status

from app.api.dependencies import ContactMessageServiceDep
from app.api.routes.portfolio.contact_message.contact_schemas import (
    ContactMessageCreateRequest,
    ContactSubmitResponse,
)

router = APIRouter(prefix="/contact", tags=["contact"])


@router.post("", response_model=ContactSubmitResponse, status_code=status.HTTP_201_CREATED)
async def submit_contact(
    body: ContactMessageCreateRequest,
    service: ContactMessageServiceDep,
) -> ContactSubmitResponse:
    await service.create(body)
    return ContactSubmitResponse(message="Message received")
