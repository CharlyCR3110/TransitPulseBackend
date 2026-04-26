from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.alert import Alert, AlertRoute


class AlertsService:
    def __init__(self, session: Session):
        self.session = session

    def list_active(self, route_ids: list[str] | None = None) -> list[dict]:
        alerts = self.session.scalars(select(Alert).where(Alert.is_active.is_(True))).all()
        route_rows = self.session.scalars(select(AlertRoute)).all()
        route_map: dict[str, list[str]] = {}
        for row in route_rows:
            route_map.setdefault(row.alert_id, []).append(row.route_id)

        results = []
        for alert in alerts:
            routes = sorted(route_map.get(alert.id, []))
            if route_ids and not set(routes).intersection(route_ids):
                continue
            results.append(
                {
                    "id": alert.id,
                    "severity": alert.severity,
                    "titleKey": alert.title_key,
                    "bodyKey": alert.body_key,
                    "emittedAt": alert.emitted_at.isoformat(),
                    "routes": routes,
                }
            )
        return results
