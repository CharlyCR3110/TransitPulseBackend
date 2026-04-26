from datetime import UTC, date, datetime, time, timedelta
from math import asin, cos, radians, sin, sqrt
import re

LAT_LNG_PATTERN = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")


def parse_lat_lng(value: str) -> tuple[float, float] | None:
    match = LAT_LNG_PATTERN.match(value)
    if match is None:
        return None
    return float(match.group(1)), float(match.group(2))


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    earth_radius_m = 6_371_000
    d_lat = radians(lat2 - lat1)
    d_lng = radians(lng2 - lng1)
    a = sin(d_lat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lng / 2) ** 2
    c = 2 * asin(sqrt(a))
    return earth_radius_m * c


def combine_today(target: time, today: date | None = None) -> datetime:
    today = today or datetime.now(UTC).date()
    return datetime.combine(today, target, tzinfo=UTC)


def time_range_to_next_departure(now: datetime, first_service: time, last_service: time, headway_minutes: int) -> datetime | None:
    first = combine_today(first_service, now.date())
    last = combine_today(last_service, now.date())
    if now <= first:
        return first
    if now > last:
        return None
    minutes_since_first = int((now - first).total_seconds() // 60)
    remainder = minutes_since_first % headway_minutes
    add_minutes = 0 if remainder == 0 else headway_minutes - remainder
    next_departure = now + timedelta(minutes=add_minutes)
    return next_departure if next_departure <= last else None


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))
