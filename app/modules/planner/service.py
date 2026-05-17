from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
from math import ceil
from typing import Any

from sqlalchemy import case, desc, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.active_trip import ActiveTrip, ActiveTripStep
from app.models.place import Place
from app.models.route import Route, RouteStop
from app.models.stop import Stop
from app.models.trip_template import TripTemplate
from app.models.user import User
from app.modules.predictions.service import PredictionsService
from app.modules.shared.exceptions import NotFoundError, ValidationAppError
from app.modules.shared.types import ActiveTripStatus, SortMode
from app.modules.shared.utils import clamp, haversine_m, parse_lat_lng


_FALLBACK_LEAVE_IN_MIN = 4
_WALKING_SPEED_M_PER_MIN = 80.0


@dataclass(frozen=True)
class _EndpointCandidate:
    stop: Stop
    lat: float
    lng: float
    walk_radius_m: float


class PlannerService:
    def __init__(self, session: Session):
        self.session = session
        self.settings = get_settings()

    def search(
        self,
        from_: str,
        to: str,
        sort: SortMode,
        now_utc: datetime | None = None,
    ) -> list[dict[str, Any]]:
        origins = self._resolve_endpoints(from_)
        destinations = self._resolve_endpoints(to)
        if not origins or not destinations:
            return []

        now_utc = now_utc or datetime.now(UTC)
        seen_hashes: set[str] = set()
        triples: list[tuple[_EndpointCandidate, _EndpointCandidate, dict[str, Any]]] = (
            []
        )
        for origin in origins:
            for destination in destinations:
                if origin.stop.id == destination.stop.id:
                    continue
                for candidate in self._build_candidates(origin, destination, now_utc):
                    signature = self._candidate_hash(
                        origin.stop.id, destination.stop.id, candidate["steps"]
                    )
                    if signature in seen_hashes:
                        continue
                    seen_hashes.add(signature)
                    triples.append((origin, destination, candidate))

        triples.sort(key=self._candidate_sort_key(sort))
        results: list[dict[str, Any]] = []
        for origin, destination, candidate in triples:
            trip = self._persist_template(
                origin.stop.id, destination.stop.id, candidate
            )
            results.append(self._trip_option_out(trip, sort.value))
        return results

    # When sorting by FASTEST, charge each transfer N "extra minutes" so that
    # a slightly-shorter transfer trip doesn't beat a clean direct trip. Real
    # transfers cost more than just headway: another fare, walking between
    # stops, and rider cognitive overhead. 7 min is the midpoint between the
    # 4-min headway-wait fudge already in the trip and the typical cost of
    # missing a connection.
    _TRANSFER_PENALTY_MIN = 7

    @staticmethod
    def _candidate_sort_key(sort: SortMode):
        if sort == SortMode.CHEAPEST:
            return lambda triple: (triple[2]["price"], triple[2]["minutes"], triple[2]["transfers"])
        if sort == SortMode.FEWEST:
            return lambda triple: (triple[2]["transfers"], triple[2]["minutes"], triple[2]["price"])
        penalty = PlannerService._TRANSFER_PENALTY_MIN
        return lambda triple: (
            triple[2]["minutes"] + penalty * triple[2]["transfers"],
            triple[2]["transfers"],
            triple[2]["price"],
        )

    def get_trip_detail(
        self, trip_id: str, departure_at: datetime | None = None
    ) -> dict[str, Any]:
        trip = self.session.get(TripTemplate, trip_id)
        if trip is None:
            raise NotFoundError("Trip not found", {"tripId": trip_id})
        return self._trip_detail_out(trip, departure_at=departure_at)

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
        candidates = self._resolve_endpoints(value)
        return candidates[0].stop if candidates else None

    def _resolve_endpoints(
        self, value: str, max_candidates: int = 5
    ) -> list[_EndpointCandidate]:
        """Return up to `max_candidates` plausible stops for the user query.
        Different sources contribute candidates so that a query like "Heredia"
        can resolve to both the 400p origin terminal AND the 400sd destination
        terminal — the search loop then tries every (origin, destination) pair."""
        parsed = parse_lat_lng(value)
        if parsed is not None:
            stop = self._nearest_stop(parsed[0], parsed[1])
            return [
                _EndpointCandidate(
                    stop=stop,
                    lat=parsed[0],
                    lng=parsed[1],
                    walk_radius_m=self.settings.boarding_walk_radius_m,
                )
            ] if stop is not None else []

        lowered = value.strip().lower()
        if not lowered:
            return []

        # Collect (stop_id, score) pairs. Note: route-name fuzzy is deliberately
        # excluded — route long-names like "Heredia - San José" contain both
        # endpoints, so the route resolver would return the first stop for
        # either query, breaking direction. Place entries cover landmark /
        # city synonyms instead.
        place_hits = self._place_candidates(lowered)
        stop_hits = self._stop_candidates(lowered)

        # If the user typed a name that EXACTLY matches a curated place
        # (score == 1.0 via ilike), trust those places exclusively. Iterating
        # fuzzy stop-label hits in that case would let the planner choose
        # intermediate stops as endpoints, which contradicts user intent
        # (typing "Heredia" means the terminal, not "PriceSmart Heredia").
        EXACT = 1.0
        has_exact_place = any(score >= EXACT for _, score in place_hits)
        sources = [place_hits] if has_exact_place else [place_hits, stop_hits]

        scored: dict[str, float] = {}
        for source in sources:
            for stop_id, score in source:
                if score < self.settings.fuzzy_threshold:
                    continue
                if scored.get(stop_id, 0.0) < score:
                    scored[stop_id] = score

        if not scored:
            return []

        ranked_ids = sorted(scored.items(), key=lambda kv: kv[1], reverse=True)
        ranked_ids = ranked_ids[:max_candidates]
        stops: list[Stop] = []
        for stop_id, _ in ranked_ids:
            stop = self.session.get(Stop, stop_id)
            if stop is not None:
                stops.append(stop)
        return [
            _EndpointCandidate(
                stop=stop,
                lat=stop.lat,
                lng=stop.lng,
                walk_radius_m=self.settings.boarding_walk_radius_m,
            )
            for stop in stops
        ]

    def _stop_candidates(self, query: str, limit: int = 5) -> list[tuple[str, float]]:
        score = func.greatest(
            func.similarity(func.lower(Stop.label_es), query),
            func.similarity(func.lower(Stop.label_en), query),
            case((func.lower(Stop.label_es).ilike(f"%{query}%"), 1.0), else_=0.0),
            case((func.lower(Stop.label_en).ilike(f"%{query}%"), 1.0), else_=0.0),
            case((func.lower(Stop.addr_es).ilike(f"%{query}%"), 0.9), else_=0.0),
            case((func.lower(Stop.addr_en).ilike(f"%{query}%"), 0.9), else_=0.0),
        ).label("score")
        rows = self.session.execute(
            select(Stop.id, score).order_by(desc(score)).limit(limit)
        ).all()
        return [(row[0], float(row[1])) for row in rows]

    def _place_candidates(self, query: str, limit: int = 5) -> list[tuple[str, float]]:
        score = func.greatest(
            func.similarity(func.lower(Place.label_es), query),
            func.similarity(func.lower(Place.label_en), query),
            case((func.lower(Place.label_es).ilike(f"%{query}%"), 1.0), else_=0.0),
            case((func.lower(Place.label_en).ilike(f"%{query}%"), 1.0), else_=0.0),
        ).label("score")
        rows = self.session.execute(
            select(Place.near_stop_id, score).order_by(desc(score)).limit(limit)
        ).all()
        return [(row[0], float(row[1])) for row in rows]

    def _route_candidates(self, query: str, limit: int = 5) -> list[tuple[str, float]]:
        """Fuzzy-match a route by its short/long name and return the route's
        first stop. Note: only the first stop — returning both endpoints would
        let queries like 'San José' resolve to the *origin* of a Heredia → SJ
        route, which is the opposite of user intent. Place entries handle
        landmark synonyms instead."""
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
        rows = self.session.execute(
            select(first_stop_subquery, score)
            .where(first_stop_subquery.is_not(None))
            .order_by(desc(score))
            .limit(limit)
        ).all()
        return [(row[0], float(row[1])) for row in rows]

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

    def _build_candidates(
        self,
        origin: Stop | _EndpointCandidate,
        destination: Stop | _EndpointCandidate,
        now_utc: datetime,
    ) -> list[dict[str, Any]]:
        origin_candidate = self._coerce_endpoint_candidate(origin)
        destination_candidate = self._coerce_endpoint_candidate(destination)
        routes = self.session.scalars(select(Route)).all()
        route_stops = self.session.scalars(
            select(RouteStop).order_by(
                RouteStop.route_id, RouteStop.direction, RouteStop.stop_order
            )
        ).all()
        route_map: dict[tuple[str, str], list[RouteStop]] = defaultdict(list)
        route_by_id = {route.id: route for route in routes}
        for item in route_stops:
            route_map[(item.route_id, item.direction)].append(item)

        candidates: list[dict[str, Any]] = []
        predictions_svc = PredictionsService(self.session)

        for (route_id, direction), stops in route_map.items():
            boarding = self._nearest_stop_on_route(origin_candidate, stops)
            alighting = self._nearest_stop_on_route(destination_candidate, stops)
            if (
                boarding is not None
                and alighting is not None
                and boarding[0] < alighting[0]
            ):
                route = route_by_id[route_id]
                origin_stop = boarding[1]
                destination_stop = alighting[1]
                leave_in_min, prediction = self._predict_leave_in(
                    predictions_svc, origin_stop.id, route_id, now_utc, direction
                )
                next_departures = self._next_departures(
                    predictions_svc, origin_stop.id, route_id, now_utc, direction
                )
                candidates.append(
                    self._direct_candidate(
                        route,
                        stops,
                        boarding[0],
                        alighting[0],
                        origin_stop,
                        destination_stop,
                        origin_candidate,
                        destination_candidate,
                        board_walk_min=boarding[3],
                        alight_walk_min=alighting[3],
                        leave_in_min=leave_in_min,
                        prediction=prediction,
                        next_departures=next_departures,
                        now_utc=now_utc,
                    )
                )

        for (route_a_id, direction_a), stops_a in route_map.items():
            boarding = self._nearest_stop_on_route(origin_candidate, stops_a)
            if boarding is None:
                continue
            for (route_b_id, _direction_b), stops_b in route_map.items():
                if route_a_id == route_b_id:
                    continue
                alighting = self._nearest_stop_on_route(destination_candidate, stops_b)
                if alighting is None:
                    continue
                for transfer_a_index, stop_a in enumerate(stops_a):
                    transfer_b_index = self._find_stop_index(stops_b, stop_a.stop_id)
                    if transfer_b_index is None:
                        continue
                    if (
                        boarding[0] < transfer_a_index < len(stops_a)
                        and transfer_b_index < alighting[0]
                    ):
                        transfer_stop = self.session.get(Stop, stop_a.stop_id)
                        if transfer_stop is None:
                            continue
                        route_a = route_by_id[route_a_id]
                        route_b = route_by_id[route_b_id]
                        origin_stop = boarding[1]
                        destination_stop = alighting[1]
                        leave_in_min, prediction = self._predict_leave_in(
                            predictions_svc,
                            origin_stop.id,
                            route_a_id,
                            now_utc,
                            direction_a,
                        )
                        next_departures = self._next_departures(
                            predictions_svc,
                            origin_stop.id,
                            route_a_id,
                            now_utc,
                            direction_a,
                        )
                        candidates.append(
                            self._transfer_candidate(
                                route_a,
                                route_b,
                                stops_a,
                                stops_b,
                                boarding[0],
                                transfer_a_index,
                                transfer_b_index,
                                alighting[0],
                                origin_stop,
                                transfer_stop,
                                destination_stop,
                                origin_candidate,
                                destination_candidate,
                                board_walk_min=boarding[3],
                                alight_walk_min=alighting[3],
                                leave_in_min=leave_in_min,
                                prediction=prediction,
                                next_departures=next_departures,
                                now_utc=now_utc,
                            )
                        )
                        break
        deduped: dict[str, dict[str, Any]] = {}
        for candidate in candidates:
            signature = self._candidate_hash(
                origin_candidate.stop.id,
                destination_candidate.stop.id,
                candidate["steps"],
            )
            deduped[signature] = candidate
        return list(deduped.values())

    def _coerce_endpoint_candidate(
        self, endpoint: Stop | _EndpointCandidate
    ) -> _EndpointCandidate:
        if isinstance(endpoint, _EndpointCandidate):
            return endpoint
        return _EndpointCandidate(
            stop=endpoint,
            lat=endpoint.lat,
            lng=endpoint.lng,
            walk_radius_m=self.settings.boarding_walk_radius_m,
        )

    def _nearest_stop_on_route(
        self, endpoint: _EndpointCandidate, route_stops: list[RouteStop]
    ) -> tuple[int, Stop, float, int] | None:
        closest: tuple[int, Stop, float, int] | None = None
        for index, route_stop in enumerate(route_stops):
            stop = self.session.get(Stop, route_stop.stop_id)
            if stop is None:
                continue
            distance_m = haversine_m(endpoint.lat, endpoint.lng, stop.lat, stop.lng)
            if distance_m > endpoint.walk_radius_m:
                continue
            walk_min = int(ceil(distance_m / _WALKING_SPEED_M_PER_MIN))
            if closest is None or distance_m < closest[2]:
                closest = (index, stop, distance_m, walk_min)
        return closest

    def _find_stop_index(self, route_stops: list[RouteStop], stop_id: str) -> int | None:
        for idx, route_stop in enumerate(route_stops):
            if route_stop.stop_id == stop_id:
                return idx
        return None

    def _build_leg_stops(
        self,
        route_stops: list[RouteStop],
        origin_index: int,
        destination_index: int,
    ) -> list[dict[str, Any]]:
        """Expand a bus leg into one entry per stop traversed (board → alight,
        inclusive). offsetFromBoardingMin is cumulative scheduled minutes from
        the boarding stop. Used by the trip detail and active-trip UIs to render
        each stop as its own card."""
        leg: list[dict[str, Any]] = []
        cumulative_min = 0
        slice_ = route_stops[origin_index : destination_index + 1]
        for sequence, route_stop in enumerate(slice_):
            if sequence > 0:
                cumulative_min += int(route_stop.segment_minutes or 0)
            stop = self.session.get(Stop, route_stop.stop_id)
            if stop is None:
                continue
            leg.append(
                {
                    "stopId": stop.id,
                    "sequence": sequence,
                    "nameEs": stop.label_es,
                    "nameEn": stop.label_en,
                    "lat": stop.lat,
                    "lng": stop.lng,
                    "offsetFromBoardingMin": cumulative_min,
                    "isBoarding": sequence == 0,
                    "isAlighting": sequence == len(slice_) - 1,
                }
            )
        return leg

    def _walk_step(
        self,
        *,
        minutes: int,
        from_stop: Stop,
        from_lat: float,
        from_lng: float,
        to_stop: Stop,
        time: str,
        to_lat: float | None = None,
        to_lng: float | None = None,
    ) -> dict[str, Any]:
        to_lat = to_stop.lat if to_lat is None else to_lat
        to_lng = to_stop.lng if to_lng is None else to_lng
        return {
            "kind": "walk",
            "minutes": minutes,
            "distanceMeters": int(round(haversine_m(from_lat, from_lng, to_lat, to_lng))),
            "fromLat": from_lat,
            "fromLng": from_lng,
            "toLat": to_lat,
            "toLng": to_lng,
            "fromEs": from_stop.label_es,
            "fromEn": from_stop.label_en,
            "toEs": to_stop.label_es,
            "toEn": to_stop.label_en,
            "time": time,
        }

    def _stamp_candidate_times(
        self, candidate: dict[str, Any], now_utc: datetime
    ) -> dict[str, Any]:
        current = now_utc
        first_bus = True
        for step in candidate["steps"]:
            if step["kind"] == "bus" and first_bus:
                start = now_utc + timedelta(minutes=candidate["leaveIn"])
                if start < current:
                    start = current
                first_bus = False
            else:
                start = current
            end = start + timedelta(minutes=step["minutes"])
            step["startsAt"] = start.isoformat()
            step["endsAt"] = end.isoformat()
            current = end
        candidate["departureAt"] = now_utc.isoformat()
        candidate["arrivalAt"] = current.isoformat()
        return candidate

    def _direct_candidate(
        self,
        route: Route,
        route_stops: list[RouteStop],
        origin_index: int,
        destination_index: int,
        origin: Stop,
        destination: Stop,
        origin_candidate: _EndpointCandidate | None = None,
        destination_candidate: _EndpointCandidate | None = None,
        board_walk_min: int = 3,
        alight_walk_min: int = 3,
        leave_in_min: int | None = None,
        prediction: dict[str, Any] | None = None,
        next_departures: list[dict[str, Any]] | None = None,
        now_utc: datetime | None = None,
    ) -> dict[str, Any]:
        origin_candidate = origin_candidate or self._coerce_endpoint_candidate(origin)
        destination_candidate = destination_candidate or self._coerce_endpoint_candidate(
            destination
        )
        ride_minutes = sum(
            item.segment_minutes
            for item in route_stops[origin_index + 1 : destination_index + 1]
        )
        route_long_name = route.long_name
        bus_step: dict[str, Any] = {
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
            "boardStopId": origin.id,
            "alightStopId": destination.id,
            "boardWalkMin": board_walk_min,
            "alightWalkMin": alight_walk_min,
            "legStops": self._build_leg_stops(
                route_stops, origin_index, destination_index
            ),
            "nextDepartures": next_departures or [],
            "routeLongNameEs": route_long_name,
            "routeLongNameEn": route_long_name,
        }
        if prediction is not None:
            bus_step["prediction"] = prediction
        steps = [
            self._walk_step(
                minutes=board_walk_min,
                from_stop=origin_candidate.stop,
                from_lat=origin_candidate.lat,
                from_lng=origin_candidate.lng,
                to_stop=origin,
                time="Ahora",
            ),
            bus_step,
            self._walk_step(
                minutes=alight_walk_min,
                from_stop=destination,
                from_lat=destination.lat,
                from_lng=destination.lng,
                to_stop=destination_candidate.stop,
                to_lat=destination_candidate.lat,
                to_lng=destination_candidate.lng,
                time=f"+{ride_minutes + alight_walk_min} min",
            ),
        ]
        candidate = {
            "minutes": ride_minutes + board_walk_min + alight_walk_min,
            "price": route.fare_min,
            "transfers": 0,
            "walkMin": board_walk_min + alight_walk_min,
            "leaveIn": (
                leave_in_min
                if leave_in_min is not None
                else _FALLBACK_LEAVE_IN_MIN
            ),
            "steps": steps,
        }
        return self._stamp_candidate_times(candidate, now_utc or datetime.now(UTC))

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
        origin_candidate: _EndpointCandidate | None = None,
        destination_candidate: _EndpointCandidate | None = None,
        board_walk_min: int = 3,
        alight_walk_min: int = 3,
        leave_in_min: int | None = None,
        prediction: dict[str, Any] | None = None,
        next_departures: list[dict[str, Any]] | None = None,
        now_utc: datetime | None = None,
    ) -> dict[str, Any]:
        origin_candidate = origin_candidate or self._coerce_endpoint_candidate(origin)
        destination_candidate = destination_candidate or self._coerce_endpoint_candidate(
            destination
        )
        ride_a = sum(
            item.segment_minutes
            for item in route_a_stops[origin_index + 1 : transfer_a_index + 1]
        )
        ride_b = sum(
            item.segment_minutes
            for item in route_b_stops[transfer_b_index + 1 : destination_index + 1]
        )
        bus_step_a: dict[str, Any] = {
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
            "boardStopId": origin.id,
            "alightStopId": transfer_stop.id,
            "boardWalkMin": board_walk_min,
            "alightWalkMin": 0,
            "legStops": self._build_leg_stops(
                route_a_stops, origin_index, transfer_a_index
            ),
            "nextDepartures": next_departures or [],
            "routeLongNameEs": route_a.long_name,
            "routeLongNameEn": route_a.long_name,
        }
        if prediction is not None:
            bus_step_a["prediction"] = prediction
        steps = [
            self._walk_step(
                minutes=board_walk_min,
                from_stop=origin_candidate.stop,
                from_lat=origin_candidate.lat,
                from_lng=origin_candidate.lng,
                to_stop=origin,
                time="Ahora",
            ),
            bus_step_a,
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
                "boardStopId": transfer_stop.id,
                "alightStopId": destination.id,
                "boardWalkMin": 0,
                "alightWalkMin": alight_walk_min,
                "legStops": self._build_leg_stops(
                    route_b_stops, transfer_b_index, destination_index
                ),
                "nextDepartures": [],
                "routeLongNameEs": route_b.long_name,
                "routeLongNameEn": route_b.long_name,
            },
            self._walk_step(
                minutes=alight_walk_min,
                from_stop=destination,
                from_lat=destination.lat,
                from_lng=destination.lng,
                to_stop=destination_candidate.stop,
                to_lat=destination_candidate.lat,
                to_lng=destination_candidate.lng,
                time=f"+{ride_a + ride_b + 4 + alight_walk_min} min",
            ),
        ]
        candidate = {
            "minutes": ride_a + ride_b + board_walk_min + alight_walk_min + 4,
            "price": route_a.fare_min + route_b.fare_min,
            "transfers": 1,
            "walkMin": board_walk_min + alight_walk_min,
            "leaveIn": leave_in_min if leave_in_min is not None else 6,
            "steps": steps,
        }
        return self._stamp_candidate_times(candidate, now_utc or datetime.now(UTC))

    @staticmethod
    def _predict_leave_in(
        predictions_svc: PredictionsService,
        origin_stop_id: str,
        route_id: str,
        now_utc: datetime,
        direction: str | None = None,
    ) -> tuple[int | None, dict[str, Any] | None]:
        """Return (leaveInMin, prediction) for the next departure of `route_id`
        at `origin_stop_id`. None if no prediction available."""
        preds = predictions_svc.predict_for_stop(
            origin_stop_id, horizon_min=60, now_utc=now_utc
        )
        for p in preds:
            if p["routeId"] != route_id:
                continue
            if direction is not None and p["direction"] != direction:
                continue
            delta_sec = (p["predictedDeparture"] - now_utc).total_seconds()
            leave_in_min = max(0, int(delta_sec // 60))
            return leave_in_min, PlannerService._prediction_payload(p)
        return None, None

    @staticmethod
    def _next_departures(
        predictions_svc: PredictionsService,
        origin_stop_id: str,
        route_id: str,
        now_utc: datetime,
        direction: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        preds = predictions_svc.predict_for_stop(
            origin_stop_id, horizon_min=90, now_utc=now_utc
        )
        for p in preds:
            if p["routeId"] != route_id:
                continue
            if direction is not None and p["direction"] != direction:
                continue
            out.append(PlannerService._prediction_payload(p))
            if len(out) >= limit:
                break
        return out

    @staticmethod
    def _prediction_payload(prediction: dict[str, Any]) -> dict[str, Any]:
        return {
            "scheduledDeparture": prediction["scheduledDeparture"].isoformat(),
            "predictedDeparture": prediction["predictedDeparture"].isoformat(),
            "windowLow": prediction["windowLow"].isoformat(),
            "windowHigh": prediction["windowHigh"].isoformat(),
            "confidence": prediction["confidence"],
            "source": prediction["source"],
        }

    def _sort_candidates(self, candidates: list[dict[str, Any]], sort: SortMode) -> list[dict[str, Any]]:
        if sort == SortMode.CHEAPEST:
            key_fn = lambda candidate: (candidate["price"], candidate["minutes"], candidate["transfers"])
        elif sort == SortMode.FEWEST:
            key_fn = lambda candidate: (candidate["transfers"], candidate["minutes"], candidate["price"])
        else:
            key_fn = lambda candidate: (candidate["minutes"], candidate["transfers"], candidate["price"])
        return sorted(candidates, key=key_fn)

    def _candidate_hash(
        self,
        origin_stop_id: str,
        destination_stop_id: str,
        steps: list[dict[str, Any]],
    ) -> str:
        signature = ";".join(
            ":".join(
                [
                    step["kind"],
                    step.get("route", ""),
                    step.get("fromEs", ""),
                    step.get("toEs", ""),
                    str(step.get("boardStopId", "")),
                    str(step.get("alightStopId", "")),
                    str(step.get("boardWalkMin", "")),
                    str(step.get("alightWalkMin", "")),
                ]
            )
            for step in steps
        )
        return hashlib.sha256(
            f"{origin_stop_id}|{destination_stop_id}|{signature}".encode("utf-8")
        ).hexdigest()

    def _persist_template(
        self,
        origin_stop_id: str,
        destination_stop_id: str,
        candidate: dict[str, Any],
    ) -> TripTemplate:
        content_hash = self._candidate_hash(origin_stop_id, destination_stop_id, candidate["steps"])
        existing = self.session.scalar(select(TripTemplate).where(TripTemplate.content_hash == content_hash))
        if existing is not None:
            existing.total_minutes = candidate["minutes"]
            existing.total_price = candidate["price"]
            existing.transfers = candidate["transfers"]
            existing.walk_min = candidate["walkMin"]
            existing.leave_in = candidate["leaveIn"]
            existing.steps = candidate["steps"]
            self.session.commit()
            self.session.refresh(existing)
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
        departure_at, arrival_at = self._step_time_envelope(trip.steps)
        return {
            "id": trip.id,
            "tag": tag,
            "departureAt": departure_at,
            "arrivalAt": arrival_at,
            "minutes": trip.total_minutes,
            "price": trip.total_price,
            "transfers": trip.transfers,
            "walkMin": trip.walk_min,
            "leaveIn": trip.leave_in,
            "confidence": self._compute_confidence(trip.transfers, trip.walk_min),
            "occupancy": self._compute_occupancy(trip.steps),
            "steps": trip.steps,
        }

    def _trip_detail_out(
        self, trip: TripTemplate, departure_at: datetime | None = None
    ) -> dict[str, Any]:
        steps = trip.steps
        leave_in = trip.leave_in
        if departure_at is not None:
            steps, leave_in = self._steps_for_departure_at(trip, departure_at)
        departure_at_out, arrival_at = self._step_time_envelope(steps)
        return {
            "id": trip.id,
            "departureAt": departure_at_out,
            "arrivalAt": arrival_at,
            "minutes": trip.total_minutes,
            "price": trip.total_price,
            "transfers": trip.transfers,
            "walkMin": trip.walk_min,
            "leaveIn": leave_in,
            "confidence": self._compute_confidence(trip.transfers, trip.walk_min),
            "occupancy": self._compute_occupancy(steps),
            "steps": steps,
        }

    def _active_trip_out(self, trip: ActiveTrip, steps: list[dict[str, Any]]) -> dict[str, Any]:
        remaining_minutes = sum(step["minutes"] for step in steps[trip.current_step_index :])
        started = int((trip.started_at or datetime.now(UTC)).timestamp() * 1000)
        departure_at, arrival_at = self._step_time_envelope(steps)
        return {
            "tripId": trip.trip_id,
            "activeTripId": trip.active_trip_id,
            "departureAt": departure_at,
            "arrivalAt": arrival_at,
            "currentStepIndex": trip.current_step_index,
            "steps": steps,
            "etaMinutes": remaining_minutes,
            "started": started,
        }

    def _steps_for_departure_at(
        self, trip: TripTemplate, departure_at: datetime
    ) -> tuple[list[dict[str, Any]], int]:
        if departure_at.tzinfo is None:
            departure_at = departure_at.replace(tzinfo=UTC)
        steps = deepcopy(trip.steps)
        leave_in = trip.leave_in
        predictions_svc = PredictionsService(self.session)

        first_bus = next((s for s in steps if s.get("kind") == "bus"), None)
        if first_bus is not None:
            route_id = str(first_bus.get("route") or "")
            board_stop_id = first_bus.get("boardStopId")
            direction = self._infer_bus_direction(
                route_id, str(board_stop_id) if board_stop_id else None, first_bus
            )
            if board_stop_id:
                leave_in_new, prediction = self._predict_leave_in(
                    predictions_svc,
                    str(board_stop_id),
                    route_id,
                    departure_at,
                    direction,
                )
                next_departures = self._next_departures(
                    predictions_svc,
                    str(board_stop_id),
                    route_id,
                    departure_at,
                    direction,
                )
                if leave_in_new is not None:
                    leave_in = leave_in_new
                if prediction is not None:
                    first_bus["prediction"] = prediction
                first_bus["nextDepartures"] = next_departures

        for step in steps:
            if step.get("kind") != "bus":
                continue
            route = self.session.get(Route, str(step.get("route") or ""))
            if route is not None:
                step["routeLongNameEs"] = route.long_name
                step["routeLongNameEn"] = route.long_name

        candidate = {
            "leaveIn": leave_in,
            "steps": steps,
            "minutes": trip.total_minutes,
            "price": trip.total_price,
            "transfers": trip.transfers,
            "walkMin": trip.walk_min,
        }
        self._stamp_candidate_times(candidate, departure_at)
        return steps, leave_in

    def _infer_bus_direction(
        self, route_id: str, board_stop_id: str | None, step: dict[str, Any]
    ) -> str | None:
        alight_stop_id = step.get("alightStopId")
        if not route_id or not board_stop_id or not alight_stop_id:
            return None
        board_rows = self.session.scalars(
            select(RouteStop)
            .where(RouteStop.route_id == route_id)
            .where(RouteStop.stop_id == board_stop_id)
        ).all()
        for board in board_rows:
            alight = self.session.scalar(
                select(RouteStop)
                .where(RouteStop.route_id == route_id)
                .where(RouteStop.stop_id == str(alight_stop_id))
                .where(RouteStop.direction == board.direction)
            )
            if alight is not None and board.stop_order < alight.stop_order:
                return board.direction
        return None

    def _compute_confidence(self, transfers: int, walk_min: int) -> float:
        return round(clamp(1.0 - 0.05 * transfers - walk_min / 60.0, 0, 1), 2)

    def _compute_occupancy(self, steps: list[dict[str, Any]]) -> int:
        occupancies = [int(step.get("occ", 0)) for step in steps if step["kind"] == "bus"]
        return max(occupancies) if occupancies else 0

    @staticmethod
    def _step_time_envelope(
        steps: list[dict[str, Any]]
    ) -> tuple[str | None, str | None]:
        if not steps:
            return None, None
        departure_at = steps[0].get("startsAt")
        arrival_at = steps[-1].get("endsAt")
        return (
            str(departure_at) if departure_at is not None else None,
            str(arrival_at) if arrival_at is not None else None,
        )
