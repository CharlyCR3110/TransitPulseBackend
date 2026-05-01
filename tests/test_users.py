from __future__ import annotations

import hashlib
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.models.active_trip import ActiveTrip
from app.models.stop import Stop
from app.models.trip_template import TripTemplate


def _ensure_trip_template(session) -> str:
    stop_id = session.scalar(select(Stop.id))
    assert stop_id is not None, "seed must contain at least one stop"
    template = TripTemplate(
        origin_stop_id=stop_id,
        destination_stop_id=stop_id,
        content_hash=hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
        total_minutes=10,
        total_price=0,
        transfers=0,
        walk_min=5,
        leave_in=0,
        steps=[],
    )
    session.add(template)
    session.flush()
    return template.id


def test_stats_requires_auth(client: TestClient) -> None:
    res = client.get("/api/v1/users/me/stats")
    assert res.status_code == 401
    body = res.json()
    assert body["error"]["code"] == "auth_required"


def test_stats_returns_zero_for_new_user(client: TestClient, register_login) -> None:
    _, token = register_login()
    res = client.get(
        "/api/v1/users/me/stats",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    assert res.json() == {"trips": 0}


def test_stats_counts_active_trips(client: TestClient, register_login) -> None:
    user_id, token = register_login()
    with SessionLocal() as session:
        template_id = _ensure_trip_template(session)
        for _ in range(3):
            session.add(ActiveTrip(trip_id=template_id, user_id=user_id))
        session.commit()

    res = client.get(
        "/api/v1/users/me/stats",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    assert res.json() == {"trips": 3}
