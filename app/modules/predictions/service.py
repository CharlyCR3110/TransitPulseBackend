from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import get_settings
from app.lib import seed_cache
from app.lib.time import (
    CR_TZ,
    at_local_date,
    hour_of_week,
    service_day_for,
    to_cr_local,
)
from app.models.delay_prior import DelayPrior
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

        cache = seed_cache.get_cache(self.session)
        serving = [
            _ServingRoute(
                route_id=e.route_id,
                route_code=e.route_code,
                direction=e.direction,
                offset_min=e.offset_min,
            )
            for e in cache.serving_by_stop.get(stop_id, [])
        ]
        if not serving:
            return []

        priors = cache.priors_by_key
        schedules = cache.schedules_by_route_dir

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
