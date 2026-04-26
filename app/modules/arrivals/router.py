from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.modules.arrivals.schemas import ArrivalOut
from app.modules.arrivals.service import ArrivalsService

router = APIRouter()


@router.get("/home", response_model=list[ArrivalOut])
def get_home_arrivals(session: Session = Depends(get_db)) -> list[dict]:
    return ArrivalsService(session).home_arrivals()


@router.get("/stops/{stop_id}", response_model=list[ArrivalOut])
def get_stop_arrivals(stop_id: str, session: Session = Depends(get_db)) -> list[dict]:
    return ArrivalsService(session).arrivals_for_stop(stop_id)
