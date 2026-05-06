from typing import Literal

from pydantic import BaseModel


Direction = Literal["outbound", "inbound"]
ServiceDay = Literal["weekday", "saturday", "sunday_holiday"]


class RouteStopOut(BaseModel):
    stopId: str
    sequence: int
    scheduledOffsetMin: int
    nameEs: str
    nameEn: str
    lat: float
    lng: float


class GeoJSONLineString(BaseModel):
    type: Literal["LineString"]
    coordinates: list[list[float]]


class DirectionOut(BaseModel):
    stops: list[RouteStopOut]
    shape: GeoJSONLineString | None = None


class ScheduleWindowOut(BaseModel):
    direction: Direction
    serviceDay: ServiceDay
    mode: Literal["headway", "explicit"]
    headwayMin: int | None = None
    startTime: str
    endTime: str
    explicitTimes: list[str] | None = None
    notes: str | None = None


class RouteOut(BaseModel):
    id: str
    code: str
    nameEs: str
    nameEn: str
    operator: str | None = None
    color: str
    fareCrc: int


class RouteDetailOut(RouteOut):
    directions: dict[Direction, DirectionOut]
    schedules: list[ScheduleWindowOut]
