from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.modules.predictions.schemas import PredictionOut
from app.modules.predictions.service import PredictionsService

router = APIRouter()


@router.get("/stop/{stop_id}", response_model=list[PredictionOut])
def predictions_for_stop(
    stop_id: str,
    horizon_min: int = 60,
    session: Session = Depends(get_db),
) -> list[dict]:
    return PredictionsService(session).predict_for_stop(
        stop_id=stop_id,
        horizon_min=horizon_min,
        now_utc=datetime.now(timezone.utc),
    )
