from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class WorkExperienceResponse(BaseModel):
    id: UUID
    sequence: int
    company: str
    company_url: str | None = None
    position: str
    location: str | None = None
    employment_type: str | None = None
    description: list[str]
    start_date: date
    end_date: date | None = None
    is_current: bool


class WorkExperienceCreateRequest(BaseModel):
    company: str = Field(..., max_length=150)
    company_url: str | None = Field(default=None, max_length=500)
    position: str = Field(..., max_length=150)
    location: str | None = Field(default=None, max_length=150)
    employment_type: str | None = Field(default=None, max_length=50)
    description: list[str] = Field(default_factory=list, max_length=60)
    start_date: date
    end_date: date | None = None
    sequence: int | None = None

    @model_validator(mode="after")
    def validate_fields(self) -> WorkExperienceCreateRequest:
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("end_date must be >= start_date")
        cleaned = [d.strip() for d in self.description if d and d.strip()]
        if len(cleaned) > 60:
            raise ValueError("description may have at most 60 items")
        self.description = cleaned
        return self


class WorkExperienceUpdateRequest(BaseModel):
    company: str | None = Field(default=None, max_length=150)
    company_url: str | None = Field(default=None, max_length=500)
    position: str | None = Field(default=None, max_length=150)
    location: str | None = Field(default=None, max_length=150)
    employment_type: str | None = Field(default=None, max_length=50)
    description: list[str] | None = Field(default=None, max_length=60)
    start_date: date | None = None
    end_date: date | None = None
    sequence: int | None = None

    @model_validator(mode="after")
    def validate_fields(self) -> WorkExperienceUpdateRequest:
        if (
            self.end_date is not None
            and self.start_date is not None
            and self.end_date < self.start_date
        ):
            raise ValueError("end_date must be >= start_date")
        if self.description is not None:
            cleaned = [d.strip() for d in self.description if d and d.strip()]
            if len(cleaned) > 60:
                raise ValueError("description may have at most 60 items")
            self.description = cleaned
        return self


class WorkExperienceListResponse(BaseModel):
    items: list[WorkExperienceResponse]
