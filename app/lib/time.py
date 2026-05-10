from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

CR_TZ = ZoneInfo("America/Costa_Rica")


def to_cr_local(utc_dt: datetime) -> datetime:
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=timezone.utc)
    return utc_dt.astimezone(CR_TZ)


def hour_of_week(local_dt: datetime) -> int:
    return local_dt.weekday() * 24 + local_dt.hour


def service_day_for(local_dt: datetime) -> str:
    wd = local_dt.weekday()
    if wd == 5:
        return "saturday"
    if wd == 6:
        return "sunday_holiday"
    return "weekday"


def at_local_date(d: date, t: time) -> datetime:
    return datetime.combine(d, t, tzinfo=CR_TZ)
