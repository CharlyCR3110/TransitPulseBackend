from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.lib import seed_cache
from app.models.alert import Alert, AlertRoute
from app.models.arrival_schedule import ArrivalSchedule
from app.models.report import Report
from app.models.report_reaction import ReportReaction
from app.models.stop import Stop
from app.modules.predictions.service import PredictionsService
from app.modules.reports.config import (
    CONFIRM_THRESHOLD,
    CROWD_DELAY_BASE_MINUTES,
    CROWD_DELAY_MAX_MINUTES,
    CROWD_DELAY_PER_CONFIRM_MINUTES,
    CROWD_DELAY_TOTAL_CAP_MINUTES,
    DELAY_REPORT_TYPES,
)
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

        route_ids = list({r["route"] for r in results})
        crowd_map = self._route_crowd_reports_map(route_ids)
        for result in results:
            summaries = crowd_map.get(result["route"])
            result["crowdReports"] = summaries if summaries else None

        delay_map = self._crowd_delay_map(crowd_map)
        occ_boost = self._crowd_occupancy_boost(crowd_map)
        for result in results:
            rid = result["route"]
            delay_sec = delay_map.get(rid, 0)
            if delay_sec > 0:
                result["etaSec"] += delay_sec
                pred = result.get("prediction")
                if pred and isinstance(pred, dict):
                    delta = timedelta(seconds=delay_sec)
                    pred["predictedDeparture"] = pred["predictedDeparture"] + delta
                    pred["windowLow"] = pred["windowLow"] + delta
                    pred["windowHigh"] = pred["windowHigh"] + delta + timedelta(minutes=1)
                    pred["crowdAdjusted"] = True
            boost = occ_boost.get(rid, 0)
            if boost > 0:
                result["occupancy"] = min(result["occupancy"] + boost, 4)

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

    def _route_crowd_reports_map(
        self, route_ids: list[str]
    ) -> dict[str, list[dict]]:
        if not route_ids:
            return {}
        now = datetime.now(UTC)
        reports = self.session.scalars(
            select(Report).where(
                Report.route_id.in_(route_ids),
                Report.expires_at > now,
                Report.status.notin_(["resolved", "dismissed"]),
            )
        ).all()

        detail_by_report: dict[int, str | None] = {}
        if reports:
            report_ids = [r.id for r in reports]
            rows = self.session.execute(
                select(
                    ReportReaction.report_id,
                    ReportReaction.detail,
                )
                .where(
                    ReportReaction.report_id.in_(report_ids),
                    ReportReaction.reaction == "confirm",
                    ReportReaction.detail.isnot(None),
                )
                .order_by(ReportReaction.created_at.desc())
            ).all()
            for report_id, detail in rows:
                detail_by_report.setdefault(report_id, detail)

        result: dict[str, list[dict]] = {}
        for report in reports:
            result.setdefault(report.route_id, []).append(
                {
                    "type": report.type,
                    "confirmCount": report.confirm_count,
                    "latestDetail": detail_by_report.get(report.id),
                }
            )
        return result

    @staticmethod
    def _crowd_delay_map(
        crowd_map: dict[str, list[dict]],
    ) -> dict[str, int]:
        """route_id → total delay in seconds from confirmed delay-type reports."""
        result: dict[str, int] = {}
        for route_id, summaries in crowd_map.items():
            total_min = 0.0
            for s in summaries:
                if s["type"] not in DELAY_REPORT_TYPES:
                    continue
                if s["confirmCount"] < CONFIRM_THRESHOLD:
                    continue
                base = CROWD_DELAY_BASE_MINUTES.get(s["type"], 3)
                per = CROWD_DELAY_PER_CONFIRM_MINUTES.get(s["type"], 1)
                cap = CROWD_DELAY_MAX_MINUTES.get(s["type"], 15)
                delay = min(base + per * s["confirmCount"], cap)
                total_min += delay
            total_min = min(total_min, CROWD_DELAY_TOTAL_CAP_MINUTES)
            if total_min > 0:
                result[route_id] = int(total_min * 60)
        return result

    @staticmethod
    def _crowd_occupancy_boost(
        crowd_map: dict[str, list[dict]],
    ) -> dict[str, int]:
        """route_id → occupancy bump from confirmed OVERCROWDING reports."""
        result: dict[str, int] = {}
        for route_id, summaries in crowd_map.items():
            boost = 0
            for s in summaries:
                if s["type"] == "OVERCROWDING" and s["confirmCount"] >= CONFIRM_THRESHOLD:
                    boost += 1
            if boost > 0:
                result[route_id] = boost
        return result

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
