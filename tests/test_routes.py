from __future__ import annotations

from fastapi.testclient import TestClient


def test_list_routes_returns_seeded_routes(client: TestClient) -> None:
    res = client.get("/api/v1/routes")
    assert res.status_code == 200, res.text
    routes = res.json()
    assert isinstance(routes, list)
    assert len(routes) >= 1
    codes = {r["code"] for r in routes}
    assert "100" in codes  # placeholder seed includes route 100
    for route in routes:
        assert {"id", "code", "nameEs", "nameEn", "color", "fareCrc"}.issubset(route)
        assert isinstance(route["fareCrc"], int)


def test_route_detail_returns_stops_and_shape(client: TestClient) -> None:
    res = client.get("/api/v1/routes/100")
    assert res.status_code == 200, res.text
    body = res.json()

    # Top-level summary fields.
    assert body["id"] == "100"
    assert body["code"] == "100"

    # Directions: at least outbound.
    assert "outbound" in body["directions"]
    outbound = body["directions"]["outbound"]
    assert isinstance(outbound["stops"], list) and outbound["stops"], "expected stops"

    sequences = [s["sequence"] for s in outbound["stops"]]
    assert sequences == sorted(sequences), "stops must be sorted by sequence"

    for stop in outbound["stops"]:
        assert {"stopId", "sequence", "scheduledOffsetMin", "lat", "lng"}.issubset(stop)
        assert isinstance(stop["lat"], float)
        assert isinstance(stop["lng"], float)

    # Shape — placeholder seed has one for route 100 outbound.
    assert outbound["shape"] is not None
    assert outbound["shape"]["type"] == "LineString"
    assert isinstance(outbound["shape"]["coordinates"], list)
    assert len(outbound["shape"]["coordinates"]) >= 2

    # Schedule windows (weekday + saturday from placeholder seed).
    schedules = body["schedules"]
    assert isinstance(schedules, list) and schedules, "expected at least one schedule"
    service_days = {s["serviceDay"] for s in schedules}
    assert "weekday" in service_days
    for s in schedules:
        assert s["mode"] in {"headway", "explicit"}
        assert isinstance(s["startTime"], str) and ":" in s["startTime"]


def test_route_detail_404_for_unknown_id(client: TestClient) -> None:
    res = client.get("/api/v1/routes/does-not-exist")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_found"
