from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.route import RouteStop
from app.models.stop import Stop
from app.modules.arrivals.service import ArrivalsService
from app.modules.shared.exceptions import NotFoundError
from app.modules.shared.utils import haversine_m


class StopsService:
    def __init__(self, session: Session):
        self.session = session

    def list_stops(self, lat: float | None = None, lng: float | None = None) -> list[dict]:
        stops = self.session.scalars(select(Stop)).all()
        route_map = self._route_map()
        return [self._serialize_stop(stop, route_map, lat, lng) for stop in stops]

    def get_stop(self, stop_id: str) -> dict:
        stop = self.session.get(Stop, stop_id)
        if stop is None:
            raise NotFoundError("Stop not found", {"stopId": stop_id})
        route_map = self._route_map()
        arrivals = ArrivalsService(self.session).arrivals_for_stop(stop_id)
        return {
            "stop": self._serialize_stop(stop, route_map),
            "arrivals": arrivals,
            "updatedAt": int(datetime.now(UTC).timestamp() * 1000),
        }

    def _route_map(self) -> dict[str, list[str]]:
        route_map: dict[str, list[str]] = {}
        for row in self.session.scalars(select(RouteStop)).all():
            route_map.setdefault(row.stop_id, []).append(row.route_id)
        return route_map

    def _serialize_stop(
        self,
        stop: Stop,
        route_map: dict[str, list[str]],
        lat: float | None = None,
        lng: float | None = None,
    ) -> dict:
        dist = 0
        if lat is not None and lng is not None:
            dist = round(haversine_m(lat, lng, stop.lat, stop.lng))
        return {
            "id": stop.id,
            "nameKey": stop.name_key,
            "addrKey": stop.addr_key,
            "dist": dist,
            "live": stop.live,
            "routes": sorted(route_map.get(stop.id, [])),
        }
