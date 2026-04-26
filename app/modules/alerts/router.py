from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.modules.alerts.schemas import AlertOut
from app.modules.alerts.service import AlertsService

router = APIRouter()


@router.get("", response_model=list[AlertOut])
def get_alerts(routeIds: str | None = None, session: Session = Depends(get_db)) -> list[dict]:
    route_ids = [item.strip() for item in routeIds.split(",")] if routeIds else None
    return AlertsService(session).list_active(route_ids)
