from __future__ import annotations

from fastapi.testclient import TestClient


def test_home_arrivals_returns_list_with_required_fields(client: TestClient) -> None:
    res = client.get("/api/v1/arrivals/home")
    assert res.status_code == 200, res.text
    body = res.json()
    assert isinstance(body, list)
    for arr in body:
        for key in ("id", "route", "kind", "destEs", "destEn", "etaSec", "status", "occupancy"):
            assert key in arr
        assert arr["etaSec"] >= 0
        # `prediction` is optional but the key must always be present (None or object).
        assert "prediction" in arr


def test_corridor_stop_arrivals_use_predictions(client: TestClient) -> None:
    """her_term_mc is on 400p (Heredia corridor) — arrivals should be backed
    by predictions, identifiable by the `pred_` id prefix and a populated
    `prediction` sub-object."""
    res = client.get("/api/v1/stops/her_term_mc")
    assert res.status_code == 200, res.text
    arrivals = res.json()["arrivals"]
    assert arrivals, "expected at least one prediction-backed arrival"
    # At least one must be a prediction.
    pred_arrivals = [a for a in arrivals if a["id"].startswith("pred_")]
    assert pred_arrivals, "expected predictions for corridor stop"
    p = pred_arrivals[0]["prediction"]
    assert p is not None
    for key in (
        "scheduledDeparture",
        "predictedDeparture",
        "windowLow",
        "windowHigh",
        "confidence",
        "source",
    ):
        assert key in p
    assert p["confidence"] in {"high", "medium", "low"}


def test_legacy_stop_arrivals_fall_back_to_schedules(client: TestClient) -> None:
    """s1 (UCR) is NOT on any M2 corridor route, so it falls back to the
    legacy `arrival_schedules` path (id prefix `arr_`, prediction is null)."""
    res = client.get("/api/v1/stops/s1")
    assert res.status_code == 200, res.text
    arrivals = res.json()["arrivals"]
    if not arrivals:
        # Outside service hours for legacy schedules — acceptable.
        return
    legacy = [a for a in arrivals if a["id"].startswith("arr_")]
    assert legacy, "expected legacy schedule-backed arrivals for s1"
    assert all(a.get("prediction") is None for a in legacy)


def test_arrivals_sorted_by_eta(client: TestClient) -> None:
    res = client.get("/api/v1/arrivals/home")
    body = res.json()
    if len(body) >= 2:
        etas = [a["etaSec"] for a in body]
        assert etas == sorted(etas)


def test_unknown_stop_arrivals_returns_404(client: TestClient) -> None:
    res = client.get("/api/v1/stops/does-not-exist")
    assert res.status_code == 404
