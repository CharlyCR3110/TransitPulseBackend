from typing import Annotated, Literal
from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.arrivals.schemas import ArrivalPrediction


class WalkStepOut(BaseModel):
    kind: Literal["walk"] = "walk"
    minutes: int
    startsAt: datetime | None = None
    endsAt: datetime | None = None
    distanceMeters: int = 0
    fromLat: float | None = None
    fromLng: float | None = None
    toLat: float | None = None
    toLng: float | None = None
    fromEs: str | None = None
    fromEn: str | None = None
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
    startsAt: datetime | None = None
    endsAt: datetime | None = None
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
    nextDepartures: list[ArrivalPrediction] = []
    routeLongNameEs: str | None = None
    routeLongNameEn: str | None = None
    prediction: ArrivalPrediction | None = None


class TransferStepOut(BaseModel):
    kind: Literal["transfer"] = "transfer"
    minutes: int
    startsAt: datetime | None = None
    endsAt: datetime | None = None
    toEs: str
    toEn: str
    time: str


TripStepOut = Annotated[WalkStepOut | BusStepOut | TransferStepOut, Field(discriminator="kind")]


class TripOptionOut(BaseModel):
    id: str
    tag: str
    departureAt: datetime | None = None
    arrivalAt: datetime | None = None
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
    departureAt: datetime | None = None
    arrivalAt: datetime | None = None
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
    departureAt: datetime | None = None
    arrivalAt: datetime | None = None
    currentStepIndex: int
    steps: list[TripStepOut]
    etaMinutes: int
    started: int


class TripAdvanceIn(BaseModel):
    currentStepIndex: int = Field(ge=0)
    activeTripId: str | None = None
