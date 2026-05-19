from pydantic import BaseModel, Field

from app.modules.reports.config import ReportType


class ReportSubmitIn(BaseModel):
    activeTripId: str
    type: ReportType
    description: str = Field(default="", max_length=500)


class ReportCreatedOut(BaseModel):
    id: int
    userId: str | None
    routeId: str | None
    direction: str | None
    stopId: str | None
    type: str
    description: str
    status: str
    confirmCount: int
    denyCount: int
    expiresAt: str | None
    createdAt: str


class ReportOut(ReportCreatedOut):
    latestDetail: str | None = None


class ReportConfirmIn(BaseModel):
    detail: str | None = Field(default=None, max_length=500)
