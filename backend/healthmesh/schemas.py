from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class CoachContext(BaseModel):
    route: str
    startDate: date | None = None
    endDate: date | None = None
    metricKeys: list[str] = Field(default_factory=list)


class CoachRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    context: CoachContext


class FeatureUnavailable(BaseModel):
    code: str = "feature_not_available"
    message: str

