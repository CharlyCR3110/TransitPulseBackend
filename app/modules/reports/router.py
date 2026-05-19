from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.dependencies import get_current_user_optional, get_db
from app.models.user import User
from app.modules.reports.schemas import ReportConfirmIn, ReportCreatedOut, ReportOut, ReportSubmitIn
from app.modules.reports.service import RateLimitExceeded, ReportExpired, ReportsService

router = APIRouter()


@router.post("", response_model=ReportCreatedOut, status_code=status.HTTP_201_CREATED)
def submit_report(
    payload: ReportSubmitIn,
    request: Request,
    session: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
) -> dict | JSONResponse:
    source_ip = request.client.host if request.client is not None else None
    try:
        return ReportsService(session).submit(payload.model_dump(), user, source_ip)
    except RateLimitExceeded:
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"detail": "Rate limit exceeded. Max 5 reports per hour."},
        )


@router.get("", response_model=list[ReportOut])
def list_reports(
    routeId: str = Query(),
    direction: str | None = Query(default=None),
    session: Session = Depends(get_db),
) -> list[dict]:
    return ReportsService(session).list_active(routeId, direction)


@router.post("/{report_id}/confirm", response_model=ReportCreatedOut)
def confirm_report(
    report_id: int,
    payload: ReportConfirmIn | None = None,
    request: Request = None,
    session: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
) -> dict | JSONResponse:
    source_ip = request.client.host if request.client is not None else None
    detail = payload.detail if payload is not None else None
    try:
        return ReportsService(session).confirm(report_id, user, source_ip, detail)
    except ReportExpired:
        return JSONResponse(
            status_code=status.HTTP_410_GONE,
            content={"detail": "Report has expired."},
        )


@router.post("/{report_id}/deny", response_model=ReportCreatedOut)
def deny_report(
    report_id: int,
    request: Request = None,
    session: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
) -> dict | JSONResponse:
    source_ip = request.client.host if request.client is not None else None
    try:
        return ReportsService(session).deny(report_id, user, source_ip)
    except ReportExpired:
        return JSONResponse(
            status_code=status.HTTP_410_GONE,
            content={"detail": "Report has expired."},
        )
