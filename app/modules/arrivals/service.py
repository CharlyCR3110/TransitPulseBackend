from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.lib import seed_cache
from app.models.alert import Alert, AlertRoute
from app.models.arrival_schedule import ArrivalSchedule
from app.models.stop import Stop
from app.modules.predictions.service import PredictionsService
from app.modules.shared.exceptions import NotFoundError
from app.modules.shared.utils import time_range_to_next_departure


class ArrivalsService:
    def __init__(self, session: Session):
        self.session = session
        self.settings = get_settings()

    def home_arrivals(self) -> list[dict]:
        cache = seed_cache.get_cache(self.session)
        live_stop_ids = [s.id for s in cache.stops_all if s.live]
        return self._compute_arrivals(
            stop_ids=live_stop_ids,
            limit=self.settings.arrivals_home_limit,
        )

    def arrivals_for_stop(self, stop_id: str) -> list[dict]:
        cache = seed_cache.get_cache(self.session)
        stop = cache.stops_by_id.get(stop_id)
        if stop is None:
            raise NotFoundError("Stop not found", {"stopId": stop_id})
        return self._compute_arrivals(stop_ids=[stop_id], limit=None)

    def _compute_arrivals(
        self, stop_ids: list[str], limit: int | None
    ) -> list[dict]:
        if not stop_ids:
            return []

        now = datetime.now(UTC)
        cache = seed_cache.get_cache(self.session)
        route_mode = {r.id: r.mode for r in cache.routes_all}
        route_terminals = self._route_terminals_from_cache(cache)
        route_status = self._route_status_map()
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
                        "status": route_status.get(p["routeId"], "ok"),
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
                        "status": route_status.get(schedule.route_id, "ok"),
                        "occupancy": schedule.occupancy,
                        "note_es": None,
                        "note_en": None,
                        "prediction": None,
                    }
                )

        ordered = sorted(results, key=lambda item: item["etaSec"])
        return ordered[:limit] if limit is not None else ordered

    @staticmethod
    def _route_terminals_from_cache(
        cache: seed_cache.SeedCache,
    ) -> dict[str, tuple[str, str]]:
        terminals: dict[str, tuple[str, str]] = {}
        for (route_id, _direction), route_stops in cache.route_stops_by_route_dir.items():
            if not route_stops:
                continue
            last = max(route_stops, key=lambda rs: rs.stop_order)
            stop = cache.stops_by_id.get(last.stop_id)
            if stop is None:
                continue
            # Direction-agnostic: outbound seen first wins. Two corridors with
            # different outbound terminals (e.g. 400p vs 400sd) end up keyed by
            # whichever direction was first iterated — fine because the home
            # screen just needs a label, not a directional commitment.
            terminals.setdefault(
                route_id, (stop.label_es or "", stop.label_en or "")
            )
        return terminals

    def _route_status_map(self) -> dict[str, str]:
        """One aggregated alert query per request, instead of N queries — one
        per prediction. Returns route_id → worst severity ("bad" > "warn" >
        "ok"). Alerts aren't in the seed cache because they can change at
        runtime; if that ever becomes a hot path, batch-load them once at
        request start (which this is)."""
        rows = self.session.execute(
            select(AlertRoute.route_id, Alert.severity)
            .join(Alert, Alert.id == AlertRoute.alert_id)
            .where(Alert.is_active.is_(True))
        ).all()
        worst: dict[str, str] = {}
        rank = {"ok": 0, "warn": 1, "bad": 2}
        for route_id, severity in rows:
            if rank.get(severity, 0) > rank.get(worst.get(route_id, "ok"), 0):
                worst[route_id] = severity
        return worst
