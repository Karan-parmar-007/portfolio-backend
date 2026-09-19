from uuid import UUID

from pydantic import BaseModel, Field


class MessageResponse(BaseModel):
    message: str


class ReorderRequest(BaseModel):
    ids: list[UUID] = Field(..., min_length=1)
