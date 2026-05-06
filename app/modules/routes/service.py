from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.route import Route, RouteStop
from app.models.route_shape import RouteShape
from app.models.schedule import Schedule
from app.models.stop import Stop
from app.modules.shared.exceptions import NotFoundError


class RoutesService:
    def __init__(self, session: Session):
        self.session = session

    def list_routes(self) -> list[dict]:
        routes = self.session.scalars(select(Route).order_by(Route.id)).all()
        return [self._serialize_summary(r) for r in routes]

    def get_route(self, route_id: str) -> dict:
        route = self.session.get(Route, route_id)
        if route is None:
            raise NotFoundError("Route not found", {"routeId": route_id})

        # Stops, joined with Stop for lat/lng + label.
        rows = self.session.execute(
            select(RouteStop, Stop)
            .join(Stop, Stop.id == RouteStop.stop_id)
            .where(RouteStop.route_id == route_id)
            .order_by(RouteStop.stop_order)
        ).all()

        directions: dict[str, dict] = defaultdict(lambda: {"stops": [], "shape": None})
        for route_stop, stop in rows:
            # Existing schema has no `direction`; default to 'outbound' for placeholder.
            directions["outbound"]["stops"].append(
                {
                    "stopId": stop.id,
                    "sequence": route_stop.stop_order,
                    "scheduledOffsetMin": route_stop.segment_minutes,
                    "nameEs": stop.label_es,
                    "nameEn": stop.label_en,
                    "lat": stop.lat,
                    "lng": stop.lng,
                }
            )

        shapes = self.session.scalars(
            select(RouteShape).where(RouteShape.route_id == route_id)
        ).all()
        for shape in shapes:
            directions.setdefault(shape.direction, {"stops": [], "shape": None})
            directions[shape.direction]["shape"] = shape.geojson

        if "outbound" not in directions:
            directions["outbound"] = {"stops": [], "shape": None}

        schedules = self.session.scalars(
            select(Schedule)
            .where(Schedule.route_id == route_id)
            .order_by(Schedule.direction, Schedule.service_day, Schedule.start_time)
        ).all()

        return {
            **self._serialize_summary(route),
            "directions": dict(directions),
            "schedules": [self._serialize_schedule(s) for s in schedules],
        }

    @staticmethod
    def _serialize_summary(route: Route) -> dict:
        return {
            "id": route.id,
            "code": route.short_name,
            "nameEs": route.long_name,
            "nameEn": route.long_name,
            "operator": None,
            "color": route.color,
            "fareCrc": route.fare_min,
        }

    @staticmethod
    def _serialize_schedule(s: Schedule) -> dict:
        return {
            "direction": s.direction,
            "serviceDay": s.service_day,
            "mode": s.mode,
            "headwayMin": s.headway_min,
            "startTime": s.start_time.strftime("%H:%M"),
            "endTime": s.end_time.strftime("%H:%M"),
            "explicitTimes": s.explicit_times,
            "notes": s.notes,
        }
