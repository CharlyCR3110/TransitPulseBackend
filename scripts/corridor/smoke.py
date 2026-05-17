"""Static smoke test for the corridor seed.

Validates:
- All seed JSON files are well-formed.
- Every row can be constructed as the SQLAlchemy model it targets (catches
  type / length errors before they hit the DB).
- Referential integrity: every route_stop.stop_id ∈ stops.id, every
  route_stop.route_id ∈ routes.id, every place.near_stop_id ∈ stops.id.
- Stop id length ≤ Stop.id column length.
- Per route+direction, stop_order is dense 1..N.

Doesn't touch the database — safe to run anywhere.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import os
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://x:x@localhost/x")
os.environ.setdefault("JWT_SECRET", "x" * 32)
os.environ.setdefault("CORS_ORIGINS", "http://x")

REPO_ROOT = Path(__file__).resolve().parents[3]
SEED_DIR = REPO_ROOT / "TransitPulseBackend/app/seed"


def _read(name: str):
    return json.loads((SEED_DIR / name).read_text(encoding="utf-8"))


def main() -> int:
    from app.models.stop import Stop
    from app.models.route import Route, RouteStop
    from app.models.place import Place

    failures: list[str] = []

    stops = _read("stops.json")
    routes = _read("routes.json")
    route_stops = _read("route_stops.json")
    places = _read("places.json")

    print(f"stops:        {len(stops)}")
    print(f"routes:       {len(routes)}")
    print(f"route_stops:  {len(route_stops)}")
    print(f"places:       {len(places)}")

    # Construct models — catches column/type violations.
    for row in stops:
        try:
            Stop(**row)
        except Exception as e:
            failures.append(f"Stop({row['id']}): {e}")

    for row in routes:
        try:
            Route(**row)
        except Exception as e:
            failures.append(f"Route({row.get('id')}): {e}")

    for row in route_stops:
        try:
            RouteStop(**row)
        except Exception as e:
            failures.append(f"RouteStop({row}): {e}")

    for row in places:
        try:
            Place(**row)
        except Exception as e:
            failures.append(f"Place({row.get('id')}): {e}")

    # Stop id length check.
    stop_id_col_len = Stop.__table__.columns["id"].type.length
    for row in stops:
        if len(row["id"]) > stop_id_col_len:
            failures.append(f"Stop({row['id']}): id length {len(row['id'])} > {stop_id_col_len}")

    # Referential integrity.
    stop_ids = {s["id"] for s in stops}
    route_ids = {r["id"] for r in routes}
    for rs in route_stops:
        if rs["stop_id"] not in stop_ids:
            failures.append(f"route_stops.stop_id orphan: {rs}")
        if rs["route_id"] not in route_ids:
            failures.append(f"route_stops.route_id orphan: {rs}")
    for p in places:
        if p["near_stop_id"] not in stop_ids:
            failures.append(f"place.near_stop_id orphan: {p['id']} → {p['near_stop_id']}")

    # Dense ordering per (route_id, direction).
    by_dir: dict[tuple[str, str], list[int]] = {}
    for rs in route_stops:
        by_dir.setdefault((rs["route_id"], rs["direction"]), []).append(rs["stop_order"])
    for (rid, dir_), orders in by_dir.items():
        orders.sort()
        if orders != list(range(1, len(orders) + 1)):
            failures.append(f"non-dense stop_order for ({rid},{dir_}): {orders}")

    # Smoke a known query: routes serving her_pricesmart_acera should include 400p inbound.
    serving = {(rs["route_id"], rs["direction"]) for rs in route_stops
               if rs["stop_id"] == "her_pricesmart_acera"}
    print(f"routes serving her_pricesmart_acera: {serving}")
    if ("400p", "inbound") not in serving:
        failures.append("expected ('400p','inbound') to serve her_pricesmart_acera")

    # And her_walmart should still be in stops.json (places.json references it).
    if "her_walmart" not in stop_ids:
        failures.append("her_walmart missing from stops.json (places.json depends on it)")

    if failures:
        print(f"\n{len(failures)} FAILURES:")
        for f in failures[:20]:
            print(f"  - {f}")
        return 1

    print("\n✓ all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
