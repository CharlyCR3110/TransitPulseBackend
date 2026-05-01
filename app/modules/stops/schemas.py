from pydantic import BaseModel

from app.modules.arrivals.schemas import ArrivalOut


class StopOut(BaseModel):
    id: str
    nameKey: str
    addrKey: str
    dist: int
    live: bool
    routes: list[str]
    lat: float
    lng: float


class StopDetailOut(BaseModel):
    stop: StopOut
    arrivals: list[ArrivalOut]
    updatedAt: int
