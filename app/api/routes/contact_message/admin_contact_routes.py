from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.all_dependencies.owner_required import require_owner
from app.api.dependencies import ContactMessageServiceDep
from app.api.routes.contact_message.contact_schemas import (
    ContactMessageResponse,
    ContactMessageUpdateRequest,
)
from app.api.schemas.pagination import PaginatedResponse, PaginationDep

router = APIRouter(
    prefix="/admin/contact-messages",
    tags=["admin:contact"],
    dependencies=[Depends(require_owner)],
)


@router.get("", response_model=PaginatedResponse[ContactMessageResponse])
async def admin_list_messages(
    service: ContactMessageServiceDep,
    pagination: PaginationDep,
) -> PaginatedResponse[ContactMessageResponse]:
    items, total = await service.list_admin(pagination)
    return PaginatedResponse.from_page(items, total=total, pagination=pagination)


@router.get("/{message_id}", response_model=ContactMessageResponse)
async def admin_get_message(
    message_id: UUID,
    service: ContactMessageServiceDep,
) -> ContactMessageResponse:
    return await service.get(message_id)


@router.patch("/{message_id}", response_model=ContactMessageResponse)
async def admin_update_message(
    message_id: UUID,
    body: ContactMessageUpdateRequest,
    service: ContactMessageServiceDep,
) -> ContactMessageResponse:
    return await service.update(message_id, body)


@router.delete("/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_delete_message(
    message_id: UUID,
    service: ContactMessageServiceDep,
) -> None:
    await service.delete(message_id)
