from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.alert import Alert, AlertRoute
from app.models.arrival_schedule import ArrivalSchedule
from app.models.route import Route, RouteStop
from app.models.stop import Stop
from app.modules.predictions.service import PredictionsService
from app.modules.shared.exceptions import NotFoundError
from app.modules.shared.utils import time_range_to_next_departure


class ArrivalsService:
    def __init__(self, session: Session):
        self.session = session
        self.settings = get_settings()

    def home_arrivals(self) -> list[dict]:
        live_stop_ids = [
            stop.id
            for stop in self.session.scalars(
                select(Stop).where(Stop.live.is_(True))
            ).all()
        ]
        return self._compute_arrivals(
            stop_ids=live_stop_ids,
            limit=self.settings.arrivals_home_limit,
        )

    def arrivals_for_stop(self, stop_id: str) -> list[dict]:
        stop = self.session.get(Stop, stop_id)
        if stop is None:
            raise NotFoundError("Stop not found", {"stopId": stop_id})
        return self._compute_arrivals(stop_ids=[stop_id], limit=None)

    def _compute_arrivals(
        self, stop_ids: list[str], limit: int | None
    ) -> list[dict]:
        if not stop_ids:
            return []

        now = datetime.now(UTC)
        route_mode = {
            route.id: route.mode
            for route in self.session.scalars(select(Route)).all()
        }
        route_terminals = self._route_terminals()
        predictions_svc = PredictionsService(self.session)

        results: list[dict] = []
        stops_with_predictions: set[str] = set()

        for sid in stop_ids:
            preds = predictions_svc.predict_for_stop(sid, now_utc=now)
            if preds:
                stops_with_predictions.add(sid)
            for p in preds:
                term_es, term_en = route_terminals.get(
                    p["routeId"], (p["routeCode"], p["routeCode"])
                )
                eta_sec = max(
                    0, int((p["predictedDeparture"] - now).total_seconds())
                )
                results.append(
                    {
                        "id": (
                            f"pred_{p['routeId']}_{sid}_"
                            f"{int(p['predictedDeparture'].timestamp())}"
                        ),
                        "route": p["routeId"],
                        "kind": route_mode.get(p["routeId"], "bus"),
                        "destEs": term_es,
                        "destEn": term_en,
                        "etaSec": eta_sec,
                        "status": self._arrival_status(p["routeId"]),
                        "occupancy": 2,
                        "note_es": None,
                        "note_en": None,
                        "prediction": {
                            "scheduledDeparture": p["scheduledDeparture"],
                            "predictedDeparture": p["predictedDeparture"],
                            "windowLow": p["windowLow"],
                            "windowHigh": p["windowHigh"],
                            "confidence": p["confidence"],
                            "source": p["source"],
                        },
                    }
                )

        fallback_ids = [s for s in stop_ids if s not in stops_with_predictions]
        if fallback_ids:
            weekday = now.weekday()
            schedules = self.session.scalars(
                select(ArrivalSchedule).where(
                    ArrivalSchedule.stop_id.in_(fallback_ids),
                    ArrivalSchedule.weekday == weekday,
                )
            ).all()
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
                        "prediction": None,
                    }
                )

        ordered = sorted(results, key=lambda item: item["etaSec"])
        return ordered[:limit] if limit is not None else ordered

    def _route_terminals(self) -> dict[str, tuple[str, str]]:
        rows = self.session.execute(
            select(RouteStop, Stop).join(Stop, Stop.id == RouteStop.stop_id)
        ).all()
        last: dict[str, tuple[int, str, str]] = {}
        for rs, stop in rows:
            current = last.get(rs.route_id)
            if current is None or rs.stop_order > current[0]:
                last[rs.route_id] = (
                    rs.stop_order,
                    stop.label_es or "",
                    stop.label_en or "",
                )
        return {rid: (es, en) for rid, (_, es, en) in last.items()}

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
