from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class EducationResponse(BaseModel):
    id: UUID
    sequence: int
    school: str
    degree: str
    field_of_study: str | None = None
    start_year: int
    end_year: int | None = None
    score: Decimal | None = None
    score_label: str | None = None
    description: str | None = None


class EducationCreateRequest(BaseModel):
    school: str = Field(..., max_length=150)
    degree: str = Field(..., max_length=150)
    field_of_study: str | None = Field(default=None, max_length=150)
    start_year: int
    end_year: int | None = None
    score: Decimal | None = Field(default=None, ge=0)
    score_label: str | None = Field(default=None, max_length=20)
    description: str | None = None
    sequence: int | None = None

    @model_validator(mode="after")
    def check_years(self) -> EducationCreateRequest:
        if self.end_year is not None and self.end_year < self.start_year:
            raise ValueError("end_year must be >= start_year")
        return self


class EducationUpdateRequest(BaseModel):
    school: str | None = Field(default=None, max_length=150)
    degree: str | None = Field(default=None, max_length=150)
    field_of_study: str | None = Field(default=None, max_length=150)
    start_year: int | None = None
    end_year: int | None = None
    score: Decimal | None = Field(default=None, ge=0)
    score_label: str | None = Field(default=None, max_length=20)
    description: str | None = None
    sequence: int | None = None

    @model_validator(mode="after")
    def check_years(self) -> EducationUpdateRequest:
        if (
            self.end_year is not None
            and self.start_year is not None
            and self.end_year < self.start_year
        ):
            raise ValueError("end_year must be >= start_year")
        return self


class EducationListResponse(BaseModel):
    items: list[EducationResponse]
