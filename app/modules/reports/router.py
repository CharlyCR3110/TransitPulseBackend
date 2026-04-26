from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.dependencies import get_current_user_optional, get_db
from app.models.user import User
from app.modules.reports.schemas import ReportCreatedOut, ReportSubmitIn
from app.modules.reports.service import ReportsService

router = APIRouter()


@router.post("", response_model=ReportCreatedOut, status_code=status.HTTP_201_CREATED)
def submit_report(
    payload: ReportSubmitIn,
    request: Request,
    session: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
) -> dict:
    source_ip = request.client.host if request.client is not None else None
    return ReportsService(session).submit(payload.model_dump(), user, source_ip)
