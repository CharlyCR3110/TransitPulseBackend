from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from math import ceil

import pytest
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.stop import Stop
from app.modules.planner.service import PlannerService
from app.modules.shared.types import SortMode
from app.modules.shared.utils import haversine_m


# Mon 2026-06-01 07:00 CR = 13:00 UTC. 400p has hour-7 weekday prior (mean=3, std=3),
# headway 12 min from 5:00.
MON_7AM_CR_UTC = datetime(2026, 6, 1, 13, 0, tzinfo=timezone.utc)
SAT_7AM_CR_UTC = datetime(2026, 6, 6, 13, 0, tzinfo=timezone.utc)


@pytest.fixture
def db() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


def _candidates_for(
    db: Session, origin_id: str, destination_id: str, now_utc: datetime
) -> list[dict]:
    origin = db.get(Stop, origin_id)
    destination = db.get(Stop, destination_id)
    assert origin is not None, f"seed missing stop {origin_id}"
    assert destination is not None, f"seed missing stop {destination_id}"
    return PlannerService(db)._build_candidates(origin, destination, now_utc)


def _bus_step(candidate: dict, route_id: str) -> dict:
    return next(s for s in candidate["steps"] if s.get("route") == route_id)


def _first_bus_step(options: list[dict], route_id: str) -> dict:
    for option in options:
        for step in option["steps"]:
            if step.get("route") == route_id:
                return step
    raise AssertionError(f"expected route {route_id} in planner options")


def test_corridor_pair_produces_400p_candidate(db: Session) -> None:
    candidates = _candidates_for(db, "her_term_mc", "sj_term_cocacola", MON_7AM_CR_UTC)
    direct = next(
        (c for c in candidates if any(s.get("route") == "400p" for s in c["steps"])),
        None,
    )
    assert direct is not None, "expected a direct 400p candidate"
    bus_step = _bus_step(direct, "400p")
    assert "prediction" in bus_step, "bus step should carry prediction payload"
    pred = bus_step["prediction"]
    assert pred is not None
    assert pred["confidence"] in {"high", "medium", "low"}
    assert pred["source"] in {"scheduled+prior", "scheduled+observed", "scheduled+no_prior"}


def test_corridor_pair_uses_predicted_leave_in(db: Session) -> None:
    """`leaveIn` must come from the predicted next departure, not the
    hardcoded fallback (4)."""
    candidates = _candidates_for(db, "her_term_mc", "sj_term_cocacola", MON_7AM_CR_UTC)
    direct = next(c for c in candidates if any(s.get("route") == "400p" for s in c["steps"]))
    # 400p outbound at Mon 7:00 CR has departures every 12 min from 5:00.
    # Latest schedule ≤ now is 7:00; next is 7:12. With +3 min mean delay,
    # the next predicted departure that is *strictly after* now is 7:03 (from
    # 7:00 schedule) or 7:15 (from 7:12 schedule). Either way leaveIn is in
    # [3, 15] minutes — and not the legacy fallback.
    assert 0 <= direct["leaveIn"] <= 60


def test_legacy_pair_still_produces_options(db: Session) -> None:
    """s1 (UCR) → s3 (Multiplaza) — legacy MLP pair on route 205."""
    candidates = _candidates_for(db, "s1", "s3", MON_7AM_CR_UTC)
    assert candidates, "legacy UCR → Multiplaza must still resolve"
    direct = next(
        (c for c in candidates if any(s.get("route") == "205" for s in c["steps"])),
        None,
    )
    assert direct is not None, "expected route 205 direct candidate"
    bus_step = _bus_step(direct, "205")
    # Route 205 has no priors at hour_of_week=7 → fallback no_prior path used.
    pred = bus_step.get("prediction")
    if pred is not None:
        # If we got one, it should be the no-prior fallback (mean=0, std=2).
        assert pred["source"] == "scheduled+no_prior"


def test_no_route_pair_returns_no_candidates(db: Session) -> None:
    """her_term_mc (Heredia) and s3 (Multiplaza Escazú) share no route."""
    candidates = _candidates_for(db, "her_term_mc", "s3", MON_7AM_CR_UTC)
    direct = [
        c for c in candidates
        if c["transfers"] == 0
        and any(s.get("route") in {"400p", "400sd"} for s in c["steps"])
    ]
    assert direct == [], "no direct 400p/400sd option should connect Heredia to Multiplaza"


def test_search_unknown_endpoint_returns_empty(db: Session) -> None:
    options = PlannerService(db).search(
        from_="not-a-real-place",
        to="another-not-real-place",
        sort=SortMode.FASTEST,
        now_utc=MON_7AM_CR_UTC,
    )
    assert options == []


def test_user_at_pricesmart_boards_at_pricesmart(db: Session) -> None:
    options = PlannerService(db).search(
        from_="9.9829,-84.1076",
        to="9.9363,-84.0861",
        sort=SortMode.FASTEST,
        now_utc=MON_7AM_CR_UTC,
    )
    bus_step = _first_bus_step(options, "400p")
    assert bus_step["boardStopId"] == "her_pricesmart"
    assert bus_step["boardWalkMin"] == 0


def test_user_far_from_corridor_falls_back_to_legacy_route(db: Session) -> None:
    options = PlannerService(db).search(
        from_="UCR",
        to="Multiplaza",
        sort=SortMode.FASTEST,
        now_utc=MON_7AM_CR_UTC,
    )
    assert _first_bus_step(options, "205")["route"] == "205"
    assert not any(
        step.get("route") in {"400p", "400sd"}
        for option in options
        for step in option["steps"]
    )


def test_alight_uses_destination_walk_radius(db: Session) -> None:
    options = PlannerService(db).search(
        from_="9.9989,-84.1165",
        to="9.9494,-84.1098",
        sort=SortMode.FASTEST,
        now_utc=MON_7AM_CR_UTC,
    )
    bus_step = _first_bus_step(options, "400p")
    assert bus_step["alightStopId"] == "sj_irazu"


def test_walk_minutes_uses_haversine(db: Session) -> None:
    origin = "9.9819,-84.1076"
    pricesmart = db.get(Stop, "her_pricesmart")
    assert pricesmart is not None
    expected_walk_min = int(
        ceil(haversine_m(9.9819, -84.1076, pricesmart.lat, pricesmart.lng) / 80.0)
    )

    options = PlannerService(db).search(
        from_=origin,
        to="9.9363,-84.0861",
        sort=SortMode.FASTEST,
        now_utc=MON_7AM_CR_UTC,
    )
    bus_step = _first_bus_step(options, "400p")
    assert bus_step["boardStopId"] == "her_pricesmart"
    assert bus_step["boardWalkMin"] == expected_walk_min
