from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.alert import Alert, AlertRoute
from app.models.arrival_schedule import ArrivalSchedule
from app.models.route import Route
from app.models.stop import Stop
from app.modules.shared.exceptions import NotFoundError
from app.modules.shared.utils import time_range_to_next_departure


class ArrivalsService:
    def __init__(self, session: Session):
        self.session = session
        self.settings = get_settings()

    def home_arrivals(self) -> list[dict]:
        live_stop_ids = [stop.id for stop in self.session.scalars(select(Stop).where(Stop.live.is_(True))).all()]
        return self._compute_arrivals(stop_ids=live_stop_ids, limit=self.settings.arrivals_home_limit)

    def arrivals_for_stop(self, stop_id: str) -> list[dict]:
        stop = self.session.get(Stop, stop_id)
        if stop is None:
            raise NotFoundError("Stop not found", {"stopId": stop_id})
        return self._compute_arrivals(stop_ids=[stop_id], limit=None)

    def _compute_arrivals(self, stop_ids: list[str], limit: int | None) -> list[dict]:
        now = datetime.now(UTC)
        weekday = now.weekday()
        route_mode = {route.id: route.mode for route in self.session.scalars(select(Route)).all()}
        schedules = self.session.scalars(
            select(ArrivalSchedule)
            .where(ArrivalSchedule.stop_id.in_(stop_ids), ArrivalSchedule.weekday == weekday)
        ).all()
        results: list[dict] = []
        for schedule in schedules:
            next_departure = time_range_to_next_departure(
                now,
                schedule.first_service,
                schedule.last_service,
                schedule.headway_minutes,
            )
            if next_departure is None:
                continue
            eta_sec = max(0, int((next_departure - now).total_seconds()))
            results.append(
                {
                    "id": f"arr_{schedule.route_id}_{schedule.stop_id}",
                    "route": schedule.route_id,
                    "kind": route_mode.get(schedule.route_id, "bus"),
                    "destEs": schedule.dest_es,
                    "destEn": schedule.dest_en,
                    "etaSec": eta_sec,
                    "status": self._arrival_status(schedule.route_id),
                    "occupancy": schedule.occupancy,
                    "note_es": None,
                    "note_en": None,
                }
            )
        ordered = sorted(results, key=lambda item: item["etaSec"])
        return ordered[:limit] if limit is not None else ordered

    def _arrival_status(self, route_id: str) -> str:
        route_alerts = self.session.scalars(
            select(Alert)
            .join(AlertRoute, AlertRoute.alert_id == Alert.id)
            .where(Alert.is_active.is_(True), AlertRoute.route_id == route_id)
        ).all()
        if not route_alerts:
            return "ok"
        severities = [alert.severity for alert in route_alerts]
        if "bad" in severities:
            return "bad"
        if "warn" in severities:
            return "warn"
        return "ok"
