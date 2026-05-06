from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.modules.routes.schemas import RouteDetailOut, RouteOut
from app.modules.routes.service import RoutesService

router = APIRouter()


@router.get("", response_model=list[RouteOut])
def list_routes(session: Session = Depends(get_db)) -> list[dict]:
    return RoutesService(session).list_routes()


@router.get("/{route_id}", response_model=RouteDetailOut)
def get_route(route_id: str, session: Session = Depends(get_db)) -> dict:
    return RoutesService(session).get_route(route_id)
