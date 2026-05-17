"""In-memory cache of small, slowly-changing seed tables.

Schedules, delay priors, routes and route_stops are tiny (≤ ~250 rows
total) and only change on reseed. Loading them once at app startup
turns the planner's per-candidate prediction loop from N+1 queries
against Neon (50+ ms RTT each) into in-memory dict lookups.

Refresh strategy: load at FastAPI startup, plus an explicit
`reload(session)` hook callable from a future admin endpoint. The
running Fly machine needs a restart after a seed change for the cache
to update; that already happens implicitly on `fly deploy`.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from threading import RLock

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.delay_prior import DelayPrior
from app.models.route import Route, RouteStop
from app.models.schedule import Schedule


@dataclass(frozen=True)
class ServingEntry:
    route_id: str
    route_code: str
    direction: str
    offset_min: int


@dataclass
class SeedCache:
    schedules_by_route_dir: dict[tuple[str, str], list[Schedule]]
    priors_by_key: dict[tuple[str, str, int], DelayPrior]
    routes_by_id: dict[str, Route]
    routes_all: list[Route]
    route_stops_by_route_dir: dict[tuple[str, str], list[RouteStop]]
    route_stops_all: list[RouteStop]
    serving_by_stop: dict[str, list[ServingEntry]]


_CACHE: SeedCache | None = None
_LOCK = RLock()


def _build_cache(session: Session) -> SeedCache:
    routes = list(session.scalars(select(Route)).all())
    route_stops = list(
        session.scalars(
            select(RouteStop).order_by(
                RouteStop.route_id, RouteStop.direction, RouteStop.stop_order
            )
        ).all()
    )
    schedules = list(session.scalars(select(Schedule)).all())
    priors = list(session.scalars(select(DelayPrior)).all())

    schedules_by_route_dir: dict[tuple[str, str], list[Schedule]] = defaultdict(list)
    for s in schedules:
        schedules_by_route_dir[(s.route_id, s.direction)].append(s)

    priors_by_key = {(p.route_id, p.direction, p.hour_of_week): p for p in priors}

    routes_by_id = {r.id: r for r in routes}

    route_stops_by_route_dir: dict[tuple[str, str], list[RouteStop]] = defaultdict(list)
    for rs in route_stops:
        route_stops_by_route_dir[(rs.route_id, rs.direction)].append(rs)

    # Precompute cumulative offsets so PredictionsService doesn't need a
    # per-call segs query. offset_min = sum of segment_minutes for stops
    # with stop_order <= target.stop_order, in the same (route_id, direction).
    serving_by_stop: dict[str, list[ServingEntry]] = defaultdict(list)
    for (route_id, direction), seq in route_stops_by_route_dir.items():
        route = routes_by_id.get(route_id)
        if route is None:
            continue
        ordered = sorted(seq, key=lambda r: r.stop_order)
        running = 0
        for rs in ordered:
            running += rs.segment_minutes or 0
            serving_by_stop[rs.stop_id].append(
                ServingEntry(
                    route_id=route_id,
                    route_code=route.short_name,
                    direction=direction,
                    offset_min=running,
                )
            )

    return SeedCache(
        schedules_by_route_dir=dict(schedules_by_route_dir),
        priors_by_key=priors_by_key,
        routes_by_id=routes_by_id,
        routes_all=routes,
        route_stops_by_route_dir=dict(route_stops_by_route_dir),
        route_stops_all=route_stops,
        serving_by_stop=dict(serving_by_stop),
    )


def get_cache(session: Session) -> SeedCache:
    """Return the cache, building it lazily on first access."""
    global _CACHE
    if _CACHE is None:
        with _LOCK:
            if _CACHE is None:
                _CACHE = _build_cache(session)
    return _CACHE


def reload(session: Session) -> SeedCache:
    """Force a fresh load. Use after a seed reload."""
    global _CACHE
    with _LOCK:
        _CACHE = _build_cache(session)
    return _CACHE


def reset_for_tests() -> None:
    """Drop the cache so the next get_cache() call rebuilds it.

    Test fixtures that mutate seed data should call this between cases."""
    global _CACHE
    with _LOCK:
        _CACHE = None
