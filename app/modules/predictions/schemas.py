from datetime import datetime
from typing import Literal

from pydantic import BaseModel

Confidence = Literal["high", "medium", "low"]
PredictionSource = Literal[
    "scheduled+prior",
    "scheduled+observed",
    "scheduled+no_prior",
]


class PredictionOut(BaseModel):
    routeId: str
    routeCode: str
    stopId: str
    direction: str
    scheduledDeparture: datetime
    predictedDeparture: datetime
    windowLow: datetime
    windowHigh: datetime
    confidence: Confidence
    source: PredictionSource
