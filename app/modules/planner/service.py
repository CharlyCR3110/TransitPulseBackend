from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
import hashlib
from typing import Any, Optional

from sqlalchemy import case, desc, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.active_trip import ActiveTrip, ActiveTripStep
from app.models.place import Place
from app.models.route import Route, RouteStop
from app.models.stop import Stop
from app.models.trip_template import TripTemplate
from app.models.user import User
from app.modules.shared.exceptions import NotFoundError, ValidationAppError
from app.modules.shared.types import ActiveTripStatus, SortMode
from app.modules.shared.utils import clamp, haversine_m, parse_lat_lng


class PlannerService:
    def __init__(self, session: Session):
        self.session = session
        self.settings = get_settings()

    def search(self, from_: str, to: str, sort: SortMode) -> list[dict[str, Any]]:
        origin = self._resolve_endpoint(from_)
        destination = self._resolve_endpoint(to)
        if origin is None or destination is None:
            return []

        candidates = self._build_candidates(origin, destination)
        ordered = self._sort_candidates(candidates, sort)
        results: list[dict[str, Any]] = []
        for candidate in ordered:
            trip = self._persist_template(origin.id, destination.id, candidate)
            results.append(self._trip_option_out(trip, sort.value))
        return results

    def get_trip_detail(self, trip_id: str) -> dict[str, Any]:
        trip = self.session.get(TripTemplate, trip_id)
        if trip is None:
            raise NotFoundError("Trip not found", {"tripId": trip_id})
        return self._trip_detail_out(trip)

    def start_trip(self, trip_id: str, user: User | None) -> dict[str, Any]:
        trip = self.session.get(TripTemplate, trip_id)
        if trip is None:
            raise NotFoundError("Trip not found", {"tripId": trip_id})

        active_trip: ActiveTrip | None = None
        if user is not None:
            active_trip = self.session.scalar(
                select(ActiveTrip)
                .where(
                    ActiveTrip.user_id == user.id,
                    ActiveTrip.status == ActiveTripStatus.IN_PROGRESS.value,
                )
            )
            if active_trip is not None and active_trip.trip_id == trip_id:
                return self._active_trip_out(active_trip, trip.steps)
            if active_trip is not None:
                active_trip.status = ActiveTripStatus.CANCELLED.value

        active_trip = ActiveTrip(
            trip_id=trip.id,
            user_id=user.id if user is not None else None,
            current_step_index=0,
            status=ActiveTripStatus.IN_PROGRESS.value,
        )
        self.session.add(active_trip)
        self.session.flush()

        for index, step in enumerate(trip.steps):
            self.session.add(
                ActiveTripStep(
                    active_trip_id=active_trip.id,
                    step_index=index,
                    kind=step["kind"],
                    route=step.get("route"),
                    time_label=step["time"],
                    minutes=step["minutes"],
                    payload=step,
                )
            )

        self.session.commit()
        self.session.refresh(active_trip)
        return self._active_trip_out(active_trip, trip.steps)

    def advance_trip(
        self,
        trip_id: str,
        current_step_index: int,
        active_trip_id: str | None,
        user: User | None,
    ) -> dict[str, Any]:
        trip = self.session.get(TripTemplate, trip_id)
        if trip is None:
            raise NotFoundError("Trip not found", {"tripId": trip_id})

        if user is None and active_trip_id is None:
            raise ValidationAppError(
                "Anonymous callers must provide activeTripId",
                {"activeTripId": "required"},
            )

        query = select(ActiveTrip).where(ActiveTrip.trip_id == trip_id)
        if active_trip_id is not None:
            query = query.where(ActiveTrip.active_trip_id == active_trip_id)
        elif user is not None:
            query = query.where(
                ActiveTrip.user_id == user.id,
                ActiveTrip.status == ActiveTripStatus.IN_PROGRESS.value,
            )

        active_trip = self.session.scalar(query)
        if active_trip is None:
            raise NotFoundError("Active trip not found", {"tripId": trip_id})

        next_index = min(current_step_index + 1, len(trip.steps) - 1)
        active_trip.current_step_index = next_index
        if next_index == len(trip.steps) - 1:
            active_trip.status = ActiveTripStatus.COMPLETED.value

        self.session.commit()
        self.session.refresh(active_trip)
        return self._active_trip_out(active_trip, trip.steps)

    def _resolve_endpoint(self, value: str) -> Stop | None:
        parsed = parse_lat_lng(value)
        if parsed is not None:
            return self._nearest_stop(parsed[0], parsed[1])
        lowered = value.strip().lower()
        if not lowered:
            return None

        candidates = [
            self._best_stop_candidate(lowered),
            self._best_place_candidate(lowered),
            self._best_route_candidate(lowered),
        ]
        valid_candidates = [candidate for candidate in candidates if candidate is not None]
        if not valid_candidates:
            return None
        best_stop_id, best_score = max(valid_candidates, key=lambda item: item[1])
        if best_score < self.settings.fuzzy_threshold:
            return None
        return self.session.get(Stop, best_stop_id)

    def _best_stop_candidate(self, query: str) -> Optional[tuple[str, float]]:
        score = func.greatest(
            func.similarity(func.lower(Stop.label_es), query),
            func.similarity(func.lower(Stop.label_en), query),
            case((func.lower(Stop.label_es).ilike(f"%{query}%"), 1.0), else_=0.0),
            case((func.lower(Stop.label_en).ilike(f"%{query}%"), 1.0), else_=0.0),
            case((func.lower(Stop.addr_es).ilike(f"%{query}%"), 0.9), else_=0.0),
            case((func.lower(Stop.addr_en).ilike(f"%{query}%"), 0.9), else_=0.0),
        ).label("score")
        row = self.session.execute(select(Stop.id, score).order_by(desc(score)).limit(1)).first()
        if row is None:
            return None
        return row[0], float(row[1])

    def _best_place_candidate(self, query: str) -> Optional[tuple[str, float]]:
        score = func.greatest(
            func.similarity(func.lower(Place.label_es), query),
            func.similarity(func.lower(Place.label_en), query),
            case((func.lower(Place.label_es).ilike(f"%{query}%"), 1.0), else_=0.0),
            case((func.lower(Place.label_en).ilike(f"%{query}%"), 1.0), else_=0.0),
        ).label("score")
        row = self.session.execute(select(Place.near_stop_id, score).order_by(desc(score)).limit(1)).first()
        if row is None:
            return None
        return row[0], float(row[1])

    def _best_route_candidate(self, query: str) -> Optional[tuple[str, float]]:
        first_stop_subquery = (
            select(RouteStop.stop_id)
            .where(RouteStop.route_id == Route.id)
            .order_by(RouteStop.stop_order)
            .limit(1)
            .scalar_subquery()
        )
        score = func.greatest(
            func.similarity(func.lower(Route.long_name), query),
            func.similarity(func.lower(Route.short_name), query),
            func.similarity(func.lower(Route.id), query),
            case((func.lower(Route.long_name).ilike(f"%{query}%"), 0.95), else_=0.0),
            case((func.lower(Route.short_name).ilike(f"%{query}%"), 0.95), else_=0.0),
            case((func.lower(Route.id).ilike(f"%{query}%"), 0.95), else_=0.0),
        ).label("score")
        row = self.session.execute(
            select(first_stop_subquery, score)
            .where(first_stop_subquery.is_not(None))
            .order_by(desc(score))
            .limit(1)
        ).first()
        if row is None:
            return None
        return row[0], float(row[1])

    def _nearest_stop(self, lat: float, lng: float) -> Stop | None:
        stops = self.session.scalars(select(Stop)).all()
        closest: tuple[float, Stop] | None = None
        for stop in stops:
            distance = haversine_m(lat, lng, stop.lat, stop.lng)
            if distance <= self.settings.nearest_stop_radius_m and (
                closest is None or distance < closest[0]
            ):
                closest = (distance, stop)
        return closest[1] if closest else None

    def _build_candidates(self, origin: Stop, destination: Stop) -> list[dict[str, Any]]:
        routes = self.session.scalars(select(Route)).all()
        route_stops = self.session.scalars(select(RouteStop).order_by(RouteStop.route_id, RouteStop.stop_order)).all()
        route_map: dict[str, list[RouteStop]] = defaultdict(list)
        route_by_id = {route.id: route for route in routes}
        for item in route_stops:
            route_map[item.route_id].append(item)

        candidates: list[dict[str, Any]] = []

        for route_id, stops in route_map.items():
            origin_index = self._find_stop_index(stops, origin.id)
            destination_index = self._find_stop_index(stops, destination.id)
            if origin_index is not None and destination_index is not None and origin_index < destination_index:
                route = route_by_id[route_id]
                candidates.append(
                    self._direct_candidate(route, stops, origin_index, destination_index, origin, destination)
                )

        for route_a_id, stops_a in route_map.items():
            origin_index = self._find_stop_index(stops_a, origin.id)
            if origin_index is None:
                continue
            for route_b_id, stops_b in route_map.items():
                if route_a_id == route_b_id:
                    continue
                destination_index = self._find_stop_index(stops_b, destination.id)
                if destination_index is None:
                    continue
                for transfer_a_index, stop_a in enumerate(stops_a):
                    transfer_b_index = self._find_stop_index(stops_b, stop_a.stop_id)
                    if transfer_b_index is None:
                        continue
                    if origin_index < transfer_a_index < len(stops_a) and transfer_b_index < destination_index:
                        transfer_stop = self.session.get(Stop, stop_a.stop_id)
                        route_a = route_by_id[route_a_id]
                        route_b = route_by_id[route_b_id]
                        candidates.append(
                            self._transfer_candidate(
                                route_a,
                                route_b,
                                stops_a,
                                stops_b,
                                origin_index,
                                transfer_a_index,
                                transfer_b_index,
                                destination_index,
                                origin,
                                transfer_stop,
                                destination,
                            )
                        )
                        break
        deduped: dict[str, dict[str, Any]] = {}
        for candidate in candidates:
            signature = self._candidate_hash(origin.id, destination.id, candidate["steps"])
            deduped[signature] = candidate
        return list(deduped.values())

    def _find_stop_index(self, route_stops: list[RouteStop], stop_id: str) -> int | None:
        for idx, route_stop in enumerate(route_stops):
            if route_stop.stop_id == stop_id:
                return idx
        return None

    def _direct_candidate(
        self,
        route: Route,
        route_stops: list[RouteStop],
        origin_index: int,
        destination_index: int,
        origin: Stop,
        destination: Stop,
    ) -> dict[str, Any]:
        ride_minutes = sum(item.segment_minutes for item in route_stops[origin_index + 1 : destination_index + 1])
        steps = [
            {
                "kind": "walk",
                "minutes": 3,
                "toEs": origin.label_es,
                "toEn": origin.label_en,
                "time": "Ahora",
            },
            {
                "kind": "bus",
                "route": route.id,
                "minutes": ride_minutes,
                "fromEs": origin.label_es,
                "fromEn": origin.label_en,
                "toEs": destination.label_es,
                "toEn": destination.label_en,
                "time": f"+{ride_minutes} min",
                "occ": 2,
                "stops": destination_index - origin_index,
            },
            {
                "kind": "walk",
                "minutes": 3,
                "toEs": destination.label_es,
                "toEn": destination.label_en,
                "time": f"+{ride_minutes + 3} min",
            },
        ]
        return {
            "minutes": ride_minutes + 6,
            "price": route.fare_min,
            "transfers": 0,
            "walkMin": 6,
            "leaveIn": 4,
            "steps": steps,
        }

    def _transfer_candidate(
        self,
        route_a: Route,
        route_b: Route,
        route_a_stops: list[RouteStop],
        route_b_stops: list[RouteStop],
        origin_index: int,
        transfer_a_index: int,
        transfer_b_index: int,
        destination_index: int,
        origin: Stop,
        transfer_stop: Stop,
        destination: Stop,
    ) -> dict[str, Any]:
        ride_a = sum(item.segment_minutes for item in route_a_stops[origin_index + 1 : transfer_a_index + 1])
        ride_b = sum(item.segment_minutes for item in route_b_stops[transfer_b_index + 1 : destination_index + 1])
        steps = [
            {
                "kind": "walk",
                "minutes": 3,
                "toEs": origin.label_es,
                "toEn": origin.label_en,
                "time": "Ahora",
            },
            {
                "kind": "bus",
                "route": route_a.id,
                "minutes": ride_a,
                "fromEs": origin.label_es,
                "fromEn": origin.label_en,
                "toEs": transfer_stop.label_es,
                "toEn": transfer_stop.label_en,
                "time": f"+{ride_a} min",
                "occ": 2,
                "stops": transfer_a_index - origin_index,
            },
            {
                "kind": "transfer",
                "minutes": 4,
                "toEs": transfer_stop.label_es,
                "toEn": transfer_stop.label_en,
                "time": f"+{ride_a + 4} min",
            },
            {
                "kind": "bus",
                "route": route_b.id,
                "minutes": ride_b,
                "fromEs": transfer_stop.label_es,
                "fromEn": transfer_stop.label_en,
                "toEs": destination.label_es,
                "toEn": destination.label_en,
                "time": f"+{ride_a + ride_b + 4} min",
                "occ": 3,
                "stops": destination_index - transfer_b_index,
            },
            {
                "kind": "walk",
                "minutes": 3,
                "toEs": destination.label_es,
                "toEn": destination.label_en,
                "time": f"+{ride_a + ride_b + 7} min",
            },
        ]
        return {
            "minutes": ride_a + ride_b + 10,
            "price": route_a.fare_min + route_b.fare_min,
            "transfers": 1,
            "walkMin": 6,
            "leaveIn": 6,
            "steps": steps,
        }

    def _sort_candidates(self, candidates: list[dict[str, Any]], sort: SortMode) -> list[dict[str, Any]]:
        if sort == SortMode.CHEAPEST:
            key_fn = lambda candidate: (candidate["price"], candidate["minutes"], candidate["transfers"])
        elif sort == SortMode.FEWEST:
            key_fn = lambda candidate: (candidate["transfers"], candidate["minutes"], candidate["price"])
        else:
            key_fn = lambda candidate: (candidate["minutes"], candidate["transfers"], candidate["price"])
        return sorted(candidates, key=key_fn)

    def _candidate_hash(self, origin_stop_id: str, destination_stop_id: str, steps: list[dict[str, Any]]) -> str:
        signature = ";".join(
            f"{step['kind']}:{step.get('route','')}:{step.get('fromEs','')}:{step.get('toEs','')}" for step in steps
        )
        return hashlib.sha256(f"{origin_stop_id}|{destination_stop_id}|{signature}".encode("utf-8")).hexdigest()

    def _persist_template(self, origin_stop_id: str, destination_stop_id: str, candidate: dict[str, Any]) -> TripTemplate:
        content_hash = self._candidate_hash(origin_stop_id, destination_stop_id, candidate["steps"])
        existing = self.session.scalar(select(TripTemplate).where(TripTemplate.content_hash == content_hash))
        if existing is not None:
            return existing

        trip = TripTemplate(
            origin_stop_id=origin_stop_id,
            destination_stop_id=destination_stop_id,
            content_hash=content_hash,
            total_minutes=candidate["minutes"],
            total_price=candidate["price"],
            transfers=candidate["transfers"],
            walk_min=candidate["walkMin"],
            leave_in=candidate["leaveIn"],
            steps=candidate["steps"],
        )
        self.session.add(trip)
        self.session.commit()
        self.session.refresh(trip)
        return trip

    def _trip_option_out(self, trip: TripTemplate, tag: str) -> dict[str, Any]:
        return {
            "id": trip.id,
            "tag": tag,
            "minutes": trip.total_minutes,
            "price": trip.total_price,
            "transfers": trip.transfers,
            "walkMin": trip.walk_min,
            "leaveIn": trip.leave_in,
            "confidence": self._compute_confidence(trip.transfers, trip.walk_min),
            "occupancy": self._compute_occupancy(trip.steps),
            "steps": trip.steps,
        }

    def _trip_detail_out(self, trip: TripTemplate) -> dict[str, Any]:
        return {
            "id": trip.id,
            "minutes": trip.total_minutes,
            "price": trip.total_price,
            "transfers": trip.transfers,
            "walkMin": trip.walk_min,
            "leaveIn": trip.leave_in,
            "confidence": self._compute_confidence(trip.transfers, trip.walk_min),
            "occupancy": self._compute_occupancy(trip.steps),
            "steps": trip.steps,
        }

    def _active_trip_out(self, trip: ActiveTrip, steps: list[dict[str, Any]]) -> dict[str, Any]:
        remaining_minutes = sum(step["minutes"] for step in steps[trip.current_step_index :])
        started = int((trip.started_at or datetime.now(UTC)).timestamp() * 1000)
        return {
            "tripId": trip.trip_id,
            "activeTripId": trip.active_trip_id,
            "currentStepIndex": trip.current_step_index,
            "steps": steps,
            "etaMinutes": remaining_minutes,
            "started": started,
        }

    def _compute_confidence(self, transfers: int, walk_min: int) -> float:
        return round(clamp(1.0 - 0.05 * transfers - walk_min / 60.0, 0, 1), 2)

    def _compute_occupancy(self, steps: list[dict[str, Any]]) -> int:
        occupancies = [int(step.get("occ", 0)) for step in steps if step["kind"] == "bus"]
        return max(occupancies) if occupancies else 0
