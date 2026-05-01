from __future__ import annotations

from fastapi.testclient import TestClient


def test_stop_out_includes_coords(client: TestClient) -> None:
    res = client.get("/api/v1/stops")
    assert res.status_code == 200
    stops = res.json()
    assert isinstance(stops, list) and stops, "expected seeded stops"
    for stop in stops:
        assert isinstance(stop["lat"], float)
        assert isinstance(stop["lng"], float)
        assert -90.0 <= stop["lat"] <= 90.0
        assert -180.0 <= stop["lng"] <= 180.0


def test_stop_detail_includes_coords(client: TestClient) -> None:
    listing = client.get("/api/v1/stops").json()
    stop_id = listing[0]["id"]
    res = client.get(f"/api/v1/stops/{stop_id}")
    assert res.status_code == 200
    body = res.json()
    assert "lat" in body["stop"]
    assert "lng" in body["stop"]
    assert isinstance(body["stop"]["lat"], float)
    assert isinstance(body["stop"]["lng"], float)
