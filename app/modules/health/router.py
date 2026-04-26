from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.modules.health.service import HealthService

router = APIRouter()


@router.get("")
def health(session: Session = Depends(get_db)) -> dict[str, str]:
    return HealthService(session).check()
