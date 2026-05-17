from typing import Annotated
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.dependencies import get_current_user_optional, get_db
from app.models.user import User
from app.modules.planner.schemas import ActiveTripOut, TripAdvanceIn, TripDetailOut, TripOptionOut
from app.modules.planner.service import PlannerService
from app.modules.shared.types import SortMode

router = APIRouter()


@router.get("/search", response_model=list[TripOptionOut])
def search_trips(
    from_: Annotated[str, Query(alias="from")],
    to: str,
    sort: SortMode = SortMode.FASTEST,
    departureAt: datetime | None = Query(default=None),
    session: Session = Depends(get_db),
) -> list[dict]:
    return PlannerService(session).search(
        from_=from_, to=to, sort=sort, now_utc=departureAt
    )


@router.get("/trips/{trip_id}", response_model=TripDetailOut)
def get_trip_detail(
    trip_id: str,
    departureAt: datetime | None = Query(default=None),
    session: Session = Depends(get_db),
) -> dict:
    return PlannerService(session).get_trip_detail(trip_id, departure_at=departureAt)


@router.post("/trips/{trip_id}/start", response_model=ActiveTripOut)
def start_trip(
    trip_id: str,
    session: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
) -> dict:
    return PlannerService(session).start_trip(trip_id, user)


@router.post("/trips/{trip_id}/advance", response_model=ActiveTripOut)
def advance_trip(
    trip_id: str,
    payload: TripAdvanceIn,
    session: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
) -> dict:
    return PlannerService(session).advance_trip(
        trip_id=trip_id,
        current_step_index=payload.currentStepIndex,
        active_trip_id=payload.activeTripId,
        user=user,
    )
