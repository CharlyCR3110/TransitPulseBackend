from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.modules.stops.schemas import StopDetailOut, StopOut
from app.modules.stops.service import StopsService

router = APIRouter()


@router.get("", response_model=list[StopOut])
def list_stops(
    lat: float | None = None,
    lng: float | None = None,
    session: Session = Depends(get_db),
) -> list[dict]:
    return StopsService(session).list_stops(lat=lat, lng=lng)


@router.get("/{stop_id}", response_model=StopDetailOut)
def get_stop(stop_id: str, session: Session = Depends(get_db)) -> dict:
    return StopsService(session).get_stop(stop_id)
