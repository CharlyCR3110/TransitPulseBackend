from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, time, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.lib.time import (
    CR_TZ,
    at_local_date,
    hour_of_week,
    service_day_for,
    to_cr_local,
)
from app.modules.predictions.service import PredictionsService


# Anchor "now" for service-level tests:
#   Monday 2026-06-01 07:00:00 America/Costa_Rica = 13:00:00 UTC.
# This is hour_of_week = 7 (Mon 7am), where 400p has prior mean=3, std=3.
MON_7AM_CR_UTC = datetime(2026, 6, 1, 13, 0, tzinfo=timezone.utc)
SAT_7AM_CR_UTC = datetime(2026, 6, 6, 13, 0, tzinfo=timezone.utc)
MON_3AM_CR_UTC = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)


@pytest.fixture
def db() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


# ── time helpers (no DB) ─────────────────────────────────────────────────────


def test_to_cr_local_no_dst() -> None:
    summer = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    winter = datetime(2026, 12, 1, 12, 0, tzinfo=timezone.utc)
    assert to_cr_local(summer).hour == 6
    assert to_cr_local(winter).hour == 6


def test_to_cr_local_treats_naive_as_utc() -> None:
    naive = datetime(2026, 6, 1, 13, 0)
    aware = datetime(2026, 6, 1, 13, 0, tzinfo=timezone.utc)
    assert to_cr_local(naive) == to_cr_local(aware)


def test_hour_of_week_monday_zero_and_sunday_last() -> None:
    mon_midnight = datetime(2026, 6, 1, 0, 0, tzinfo=CR_TZ)
    sun_2300 = datetime(2026, 6, 7, 23, 0, tzinfo=CR_TZ)
    assert hour_of_week(mon_midnight) == 0
    assert hour_of_week(sun_2300) == 167


def test_service_day_for_buckets() -> None:
    mon = datetime(2026, 6, 1, 12, 0, tzinfo=CR_TZ)
    sat = datetime(2026, 6, 6, 12, 0, tzinfo=CR_TZ)
    sun = datetime(2026, 6, 7, 12, 0, tzinfo=CR_TZ)
    assert service_day_for(mon) == "weekday"
    assert service_day_for(sat) == "saturday"
    assert service_day_for(sun) == "sunday_holiday"


def test_at_local_date_is_tz_aware() -> None:
    d = at_local_date(datetime(2026, 6, 1).date(), time(7, 30))
    assert d.tzinfo is not None
    assert d.utcoffset().total_seconds() == -6 * 3600


# ── service-level (real DB) ──────────────────────────────────────────────────


def test_unknown_stop_returns_empty(db: Session) -> None:
    out = PredictionsService(db).predict_for_stop(
        "stop_does_not_exist", now_utc=MON_7AM_CR_UTC
    )
    assert out == []


def test_predict_for_origin_stop_returns_eta_with_band(db: Session) -> None:
    out = PredictionsService(db).predict_for_stop(
        "her_term_mc", horizon_min=60, now_utc=MON_7AM_CR_UTC
    )
    assert out, "expected at least one 400p prediction at Mon 7am peak"

    p = out[0]
    assert p["routeId"] == "400p"
    assert p["direction"] == "outbound"
    assert p["stopId"] == "her_term_mc"
    # Mon 7am prior for 400p has mean=3, std=3 → window ±5.88 min around predicted.
    assert p["predictedDeparture"] >= p["scheduledDeparture"]
    assert p["windowLow"] <= p["predictedDeparture"] <= p["windowHigh"]
    assert p["confidence"] in {"high", "medium", "low"}
    assert p["source"] in {"scheduled+prior", "scheduled+observed"}


def test_intermediate_stop_uses_cumulative_offset(db: Session) -> None:
    """her_pricesmart is the 3rd stop on 400p with cumulative offset 8 min from
    origin (segments 0+3+5). A 7:00 origin departure must arrive there at 7:08,
    NOT at 7:05 (per-segment misuse) and NOT at 7:00 (zero-offset bug)."""
    out = PredictionsService(db).predict_for_stop(
        "her_pricesmart", horizon_min=60, now_utc=MON_7AM_CR_UTC
    )
    assert out, "expected predictions at her_pricesmart"

    # Find the prediction whose scheduledDeparture lands exactly on a 7:08-style
    # arrival (origin 7:00 + 8 min). We accept any prediction whose minute is
    # NOT one of {00, 12, 24, 36, 48} — those would be the origin departure
    # times, which would indicate offset_min was treated as 0.
    cr_minutes = {
        p["scheduledDeparture"].astimezone(CR_TZ).minute for p in out
    }
    origin_only_minutes = {0, 12, 24, 36, 48}
    assert not cr_minutes.issubset(origin_only_minutes), (
        f"scheduled departures at her_pricesmart should be offset from origin "
        f"departures by 8 min, but got minutes {cr_minutes} "
        f"(would match origin if offset bug)"
    )


def test_predictions_sorted_by_predicted_departure(db: Session) -> None:
    out = PredictionsService(db).predict_for_stop(
        "her_term_mc", horizon_min=60, now_utc=MON_7AM_CR_UTC
    )
    assert len(out) >= 2
    times = [p["predictedDeparture"] for p in out]
    assert times == sorted(times)


def test_horizon_filter_shrinks_results(db: Session) -> None:
    long = PredictionsService(db).predict_for_stop(
        "her_term_mc", horizon_min=60, now_utc=MON_7AM_CR_UTC
    )
    short = PredictionsService(db).predict_for_stop(
        "her_term_mc", horizon_min=10, now_utc=MON_7AM_CR_UTC
    )
    assert len(short) <= len(long)
    # Every short-horizon prediction is within 10 min + buffer of now.
    for p in short:
        delta = (
            p["predictedDeparture"] - MON_7AM_CR_UTC
        ).total_seconds() / 60.0
        assert delta <= 15.0  # 10 min horizon + ~5 min for delay band


def test_no_prior_falls_back_to_no_prior_source(db: Session) -> None:
    """Saturday 7am CR has NO 400p prior at hour_of_week=127, so service must
    fall back to mean=0, std=2, source='scheduled+no_prior'."""
    out = PredictionsService(db).predict_for_stop(
        "her_term_mc", horizon_min=60, now_utc=SAT_7AM_CR_UTC
    )
    assert out
    assert all(p["routeId"] == "400p" for p in out)
    assert all(p["source"] == "scheduled+no_prior" for p in out)
    # mean=0 → predicted == scheduled.
    for p in out:
        assert p["predictedDeparture"] == p["scheduledDeparture"]


def test_24x7_route_returns_predictions_at_3am(db: Session) -> None:
    """400sd runs 24/7. At Mon 3am CR (hour_of_week=3) it should still return
    predictions for sd_plaza."""
    out = PredictionsService(db).predict_for_stop(
        "sd_plaza", horizon_min=60, now_utc=MON_3AM_CR_UTC
    )
    assert out, "expected 400sd predictions at 3am (24/7 service)"
    assert all(p["routeId"] == "400sd" for p in out)


def test_confidence_buckets(db: Session) -> None:
    """std=3 on 400p at Mon 7am should fall in 'medium' (2.0 ≤ 3 < 5.0)."""
    out = PredictionsService(db).predict_for_stop(
        "her_term_mc", horizon_min=60, now_utc=MON_7AM_CR_UTC
    )
    assert out
    assert out[0]["confidence"] == "medium"


def test_predictions_capped_at_max_per_stop(db: Session) -> None:
    out = PredictionsService(db).predict_for_stop(
        "her_term_mc", horizon_min=24 * 60, now_utc=MON_7AM_CR_UTC
    )
    # Settings default predictions_max_per_stop = 10.
    assert len(out) <= 10


# ── HTTP-level smoke ─────────────────────────────────────────────────────────


def test_http_unknown_stop_returns_empty_list(client: TestClient) -> None:
    res = client.get("/api/v1/predictions/stop/does_not_exist")
    assert res.status_code == 200
    assert res.json() == []


def test_http_known_stop_returns_list(client: TestClient) -> None:
    res = client.get("/api/v1/predictions/stop/her_term_mc?horizon_min=60")
    assert res.status_code == 200
    body = res.json()
    assert isinstance(body, list)
    if body:
        p = body[0]
        for key in (
            "routeId",
            "routeCode",
            "stopId",
            "direction",
            "scheduledDeparture",
            "predictedDeparture",
            "windowLow",
            "windowHigh",
            "confidence",
            "source",
        ):
            assert key in p
