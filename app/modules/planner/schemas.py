from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.modules.arrivals.schemas import ArrivalPrediction


class WalkStepOut(BaseModel):
    kind: Literal["walk"] = "walk"
    minutes: int
    toEs: str
    toEn: str
    time: str


class BusLegStop(BaseModel):
    """One stop the bus passes through during this leg, ordered from
    boarding (sequence=0) to alighting (sequence=N-1)."""
    stopId: str
    sequence: int
    nameEs: str
    nameEn: str
    lat: float
    lng: float
    """Cumulative scheduled minutes from the boarding stop. 0 at the
    boarding stop, total ride time at the alighting stop."""
    offsetFromBoardingMin: int
    isBoarding: bool = False
    isAlighting: bool = False


class BusStepOut(BaseModel):
    kind: Literal["bus"] = "bus"
    route: str
    minutes: int
    fromEs: str
    fromEn: str
    toEs: str
    toEn: str
    time: str
    occ: int
    stops: int
    boardStopId: str | None = None
    alightStopId: str | None = None
    boardWalkMin: int = 3
    alightWalkMin: int = 3
    legStops: list[BusLegStop] = []
    prediction: ArrivalPrediction | None = None


class TransferStepOut(BaseModel):
    kind: Literal["transfer"] = "transfer"
    minutes: int
    toEs: str
    toEn: str
    time: str


TripStepOut = Annotated[WalkStepOut | BusStepOut | TransferStepOut, Field(discriminator="kind")]


class TripOptionOut(BaseModel):
    id: str
    tag: str
    minutes: int
    price: int
    transfers: int
    walkMin: int
    leaveIn: int
    confidence: float
    occupancy: int
    steps: list[TripStepOut]


class TripDetailOut(BaseModel):
    id: str
    minutes: int
    price: int
    transfers: int
    walkMin: int
    leaveIn: int
    confidence: float
    occupancy: int
    steps: list[TripStepOut]


class ActiveTripOut(BaseModel):
    tripId: str
    activeTripId: str
    currentStepIndex: int
    steps: list[TripStepOut]
    etaMinutes: int
    started: int


class TripAdvanceIn(BaseModel):
    currentStepIndex: int = Field(ge=0)
    activeTripId: str | None = None
