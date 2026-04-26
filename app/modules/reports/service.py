from sqlalchemy.orm import Session

from app.models.report import Report
from app.models.user import User


class ReportsService:
    def __init__(self, session: Session):
        self.session = session

    def submit(self, payload: dict, user: User | None, source_ip: str | None) -> dict:
        report = Report(
            user_id=user.id if user is not None else None,
            route_id=payload.get("routeId"),
            stop_id=payload.get("stopId"),
            type=payload["type"],
            description=payload["description"],
            source_ip=source_ip,
        )
        self.session.add(report)
        self.session.commit()
        self.session.refresh(report)
        return {
            "id": report.id,
            "userId": report.user_id,
            "routeId": report.route_id,
            "stopId": report.stop_id,
            "type": report.type,
            "description": report.description,
            "status": report.status,
            "createdAt": report.created_at.isoformat(),
        }
