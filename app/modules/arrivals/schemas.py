from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.modules.predictions.schemas import Confidence, PredictionSource


class ArrivalPrediction(BaseModel):
    scheduledDeparture: datetime
    predictedDeparture: datetime
    windowLow: datetime
    windowHigh: datetime
    confidence: Confidence
    source: PredictionSource


class CrowdReportSummary(BaseModel):
    type: str
    confirmCount: int
    latestDetail: str | None = None


class ArrivalOut(BaseModel):
    id: str
    route: str
    kind: Literal["bus", "train"]
    destEs: str
    destEn: str
    etaSec: int
    status: str
    occupancy: int
    note_es: str | None = None
    note_en: str | None = None
    prediction: ArrivalPrediction | None = None
    crowdReports: list[CrowdReportSummary] | None = None
