from __future__ import annotations

import json
from datetime import UTC, datetime, time
from pathlib import Path

from sqlalchemy import delete, text

from app.db import Base, SessionLocal, engine
from app.models.active_trip import ActiveTrip, ActiveTripStep
from app.models.alert import Alert, AlertRoute
from app.models.arrival_schedule import ArrivalSchedule
from app.models.delay_prior import DelayPrior
from app.models.place import Place
from app.models.route import Route, RouteStop
from app.models.route_shape import RouteShape
from app.models.schedule import Schedule
from app.models.stop import Stop
from app.models.trip_template import TripTemplate

SEED_DIR = Path(__file__).resolve().parent


def _read_json(filename: str) -> list[dict]:
    return json.loads((SEED_DIR / filename).read_text(encoding="utf-8"))


def _parse_time(value: str) -> time:
    return time.fromisoformat(value)


def load_seed() -> None:
    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as session:
        session.execute(delete(ActiveTripStep))
        session.execute(delete(ActiveTrip))
        session.execute(delete(TripTemplate))
        session.execute(delete(AlertRoute))
        session.execute(delete(Alert))
        session.execute(delete(ArrivalSchedule))
        session.execute(delete(DelayPrior))
        session.execute(delete(Schedule))
        session.execute(delete(RouteShape))
        session.execute(delete(RouteStop))
        session.execute(delete(Place))
        session.execute(delete(Route))
        session.execute(delete(Stop))

        for item in _read_json("stops.json"):
            session.add(Stop(**item))

        for item in _read_json("routes.json"):
            session.add(Route(**item))
        session.flush()

        for item in _read_json("route_stops.json"):
            session.add(RouteStop(**item))
        session.flush()

        for item in _read_json("route_shapes.json"):
            session.add(RouteShape(**item))

        for item in _read_json("schedules.json"):
            session.add(
                Schedule(
                    route_id=item["route_id"],
                    direction=item["direction"],
                    service_day=item["service_day"],
                    mode=item["mode"],
                    headway_min=item["headway_min"],
                    start_time=_parse_time(item["start_time"]),
                    end_time=_parse_time(item["end_time"]),
                    explicit_times=item["explicit_times"],
                    notes=item["notes"],
                )
            )

        for item in _read_json("delay_priors.json"):
            session.add(DelayPrior(**item))
        session.flush()

        emitted_at = datetime.now(UTC)
        for item in _read_json("alerts.json"):
            payload = dict(item)
            routes = payload.pop("routes")
            session.add(Alert(**payload, emitted_at=emitted_at, is_active=True))
            session.flush()
            for route_id in routes:
                session.add(AlertRoute(alert_id=payload["id"], route_id=route_id))

        for item in _read_json("places.json"):
            session.add(Place(**item))

        schedules = _read_json("arrival_schedules.json")
        expanded: list[dict] = []
        for item in schedules:
            if item["weekday"] == 0:
                for weekday in range(7):
                    clone = dict(item)
                    clone["weekday"] = weekday
                    expanded.append(clone)
            else:
                expanded.append(item)

        for item in expanded:
            session.add(
                ArrivalSchedule(
                    route_id=item["route_id"],
                    stop_id=item["stop_id"],
                    weekday=item["weekday"],
                    first_service=_parse_time(item["first_service"]),
                    last_service=_parse_time(item["last_service"]),
                    headway_minutes=item["headway_minutes"],
                    dest_es=item["dest_es"],
                    dest_en=item["dest_en"],
                    occupancy=item["occupancy"],
                )
            )

        session.commit()


if __name__ == "__main__":
    load_seed()
