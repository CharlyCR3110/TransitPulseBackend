from pydantic import BaseModel, Field


class ReportSubmitIn(BaseModel):
    type: str
    routeId: str | None = None
    stopId: str | None = None
    description: str = Field(min_length=1, max_length=2000)


class ReportCreatedOut(BaseModel):
    id: int
    userId: str | None
    routeId: str | None
    stopId: str | None
    type: str
    description: str
    status: str
    createdAt: str
