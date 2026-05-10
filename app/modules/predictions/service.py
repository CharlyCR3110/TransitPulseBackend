from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.lib.time import (
    CR_TZ,
    at_local_date,
    hour_of_week,
    service_day_for,
    to_cr_local,
)
from app.models.delay_prior import DelayPrior
from app.models.route import Route, RouteStop
from app.models.schedule import Schedule


@dataclass
class _ServingRoute:
    route_id: str
    route_code: str
    direction: str
    offset_min: int  # cumulative minutes from origin departure to this stop


class PredictionsService:
    def __init__(self, session: Session):
        self.session = session
        self.settings = get_settings()

    def predict_for_stop(
        self,
        stop_id: str,
        horizon_min: int | None = None,
        now_utc: datetime | None = None,
    ) -> list[dict]:
        horizon = horizon_min or self.settings.predictions_default_horizon_min
        now_utc = now_utc or datetime.now(timezone.utc)
        now_local = to_cr_local(now_utc)
        until_local = now_local + timedelta(minutes=horizon)

        serving = self._routes_serving_stop(stop_id)
        if not serving:
            return []

        route_dir_pairs = {(s.route_id, s.direction) for s in serving}
        priors = self._load_priors(route_dir_pairs)
        schedules = self._load_schedules(route_dir_pairs)

        out: list[dict] = []
        for s in serving:
            for sched in schedules.get((s.route_id, s.direction), []):
                for sched_dep_local in self._walk_schedule(
                    sched, now_local, until_local, s.offset_min
                ):
                    pred = self._predict_one(
                        s, sched_dep_local, priors, stop_id, now_local
                    )
                    if pred is not None:
                        out.append(pred)

        out.sort(key=lambda p: p["predictedDeparture"])
        return out[: self.settings.predictions_max_per_stop]

    def _routes_serving_stop(self, stop_id: str) -> list[_ServingRoute]:
        # Find every route that has the requested stop, then for each route
        # compute the cumulative offset from origin (sum of segment_minutes
        # from stop_order=1 through this stop's stop_order). segment_minutes
        # in the seed is the per-segment delta, not a cumulative offset.
        target_rows = self.session.execute(
            select(RouteStop, Route)
            .join(Route, Route.id == RouteStop.route_id)
            .where(RouteStop.stop_id == stop_id)
        ).all()
        if not target_rows:
            return []

        results: list[_ServingRoute] = []
        for target_rs, route in target_rows:
            segs = self.session.scalars(
                select(RouteStop)
                .where(RouteStop.route_id == target_rs.route_id)
                .where(RouteStop.direction == target_rs.direction)
                .where(RouteStop.stop_order <= target_rs.stop_order)
                .order_by(RouteStop.stop_order)
            ).all()
            offset = sum(rs.segment_minutes or 0 for rs in segs)
            results.append(
                _ServingRoute(
                    route_id=target_rs.route_id,
                    route_code=route.short_name,
                    direction=target_rs.direction,
                    offset_min=offset,
                )
            )
        return results

    def _load_priors(
        self, pairs: set[tuple[str, str]]
    ) -> dict[tuple[str, str, int], DelayPrior]:
        if not pairs:
            return {}
        route_ids = {p[0] for p in pairs}
        rows = self.session.scalars(
            select(DelayPrior).where(DelayPrior.route_id.in_(route_ids))
        ).all()
        return {(r.route_id, r.direction, r.hour_of_week): r for r in rows}

    def _load_schedules(
        self, pairs: set[tuple[str, str]]
    ) -> dict[tuple[str, str], list[Schedule]]:
        if not pairs:
            return {}
        route_ids = {p[0] for p in pairs}
        rows = self.session.scalars(
            select(Schedule).where(Schedule.route_id.in_(route_ids))
        ).all()
        bucket: dict[tuple[str, str], list[Schedule]] = defaultdict(list)
        for s in rows:
            bucket[(s.route_id, s.direction)].append(s)
        return bucket

    def _walk_schedule(
        self,
        schedule: Schedule,
        now_local: datetime,
        until_local: datetime,
        offset_min: int,
    ) -> list[datetime]:
        candidates: list[datetime] = []
        for d in (now_local.date(), now_local.date() + timedelta(days=1)):
            probe = at_local_date(d, time(0, 0))
            if service_day_for(probe) != schedule.service_day:
                continue
            for origin in self._schedule_origin_starts(schedule, d):
                at_stop = origin + timedelta(minutes=offset_min)
                if now_local <= at_stop <= until_local:
                    candidates.append(at_stop)
        return candidates

    @staticmethod
    def _schedule_origin_starts(schedule: Schedule, d: date) -> list[datetime]:
        if schedule.mode == "explicit" and schedule.explicit_times:
            return [
                at_local_date(d, time.fromisoformat(t))
                for t in schedule.explicit_times
            ]
        if schedule.headway_min is None or schedule.headway_min <= 0:
            return []
        start = at_local_date(d, schedule.start_time)
        end = at_local_date(d, schedule.end_time)
        out: list[datetime] = []
        cur = start
        while cur <= end:
            out.append(cur)
            cur = cur + timedelta(minutes=schedule.headway_min)
        return out

    def _predict_one(
        self,
        s: _ServingRoute,
        sched_dep_local: datetime,
        priors: dict[tuple[str, str, int], DelayPrior],
        stop_id: str,
        now_local: datetime,
    ) -> dict | None:
        how = hour_of_week(sched_dep_local)
        prior = priors.get((s.route_id, s.direction, how))
        if prior is None:
            mean, std, source = 0.0, 2.0, "scheduled+no_prior"
        else:
            mean = prior.mean_delay_min
            std = prior.std_delay_min
            source = (
                "scheduled+observed"
                if prior.n_observations > 0
                else "scheduled+prior"
            )

        predicted_local = sched_dep_local + timedelta(minutes=mean)
        if predicted_local <= now_local:
            return None

        half_band = timedelta(minutes=1.96 * std)
        return {
            "routeId": s.route_id,
            "routeCode": s.route_code,
            "stopId": stop_id,
            "direction": s.direction,
            "scheduledDeparture": sched_dep_local.astimezone(timezone.utc),
            "predictedDeparture": predicted_local.astimezone(timezone.utc),
            "windowLow": (predicted_local - half_band).astimezone(timezone.utc),
            "windowHigh": (predicted_local + half_band).astimezone(timezone.utc),
            "confidence": self._confidence_bucket(std),
            "source": source,
        }

    def _confidence_bucket(self, std_min: float) -> str:
        lo, hi = self.settings.predictions_confidence_thresholds
        if std_min < lo:
            return "high"
        if std_min < hi:
            return "medium"
        return "low"
