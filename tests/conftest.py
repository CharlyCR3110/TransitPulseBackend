from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://transitpulse:transitpulse@localhost:5433/transitpulse",
)
os.environ.setdefault("JWT_SECRET", "dev-only-secret-change-me-32-bytes-min")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:3000")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.db import SessionLocal
from app.main import app
from app.models.active_trip import ActiveTrip, ActiveTripStep
from app.models.user import User


@pytest.fixture(scope="session")
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


@pytest.fixture
def created_user_ids() -> Iterator[list[str]]:
    ids: list[str] = []
    yield ids
    if not ids:
        return
    with SessionLocal() as session:
        session.execute(
            delete(ActiveTripStep).where(
                ActiveTripStep.active_trip_id.in_(
                    session.query(ActiveTrip.id).filter(ActiveTrip.user_id.in_(ids))
                )
            )
        )
        session.execute(delete(ActiveTrip).where(ActiveTrip.user_id.in_(ids)))
        session.execute(delete(User).where(User.id.in_(ids)))
        session.commit()


@pytest.fixture
def register_login(client: TestClient, created_user_ids: list[str]):
    def _register_login(password: str = "Password123!") -> tuple[str, str]:
        email = f"pytest+{uuid.uuid4().hex[:10]}@example.com"
        reg = client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": password, "displayName": "Pytest"},
        )
        assert reg.status_code == 201, reg.text
        created_user_ids.append(reg.json()["id"])
        login = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )
        assert login.status_code == 200, login.text
        return reg.json()["id"], login.json()["accessToken"]

    return _register_login
