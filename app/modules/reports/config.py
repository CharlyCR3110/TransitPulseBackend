from datetime import datetime, timedelta
from enum import StrEnum


class ReportType(StrEnum):
    DELAY = "DELAY"
    BREAKDOWN = "BREAKDOWN"
    ACCIDENT = "ACCIDENT"
    OVERCROWDING = "OVERCROWDING"
    ROUTE_CHANGE = "ROUTE_CHANGE"
    SAFETY = "SAFETY"
    OTHER = "OTHER"


REPORT_TTL_MINUTES: dict[str, int] = {
    ReportType.DELAY: 30,
    ReportType.OVERCROWDING: 20,
    ReportType.BREAKDOWN: 60,
    ReportType.ACCIDENT: 120,
    ReportType.ROUTE_CHANGE: 120,
    ReportType.SAFETY: 60,
    ReportType.OTHER: 30,
}

REPORT_CONFIRM_EXTENSION_MINUTES: dict[str, int] = {
    ReportType.DELAY: 15,
    ReportType.OVERCROWDING: 10,
    ReportType.BREAKDOWN: 30,
    ReportType.ACCIDENT: 30,
    ReportType.ROUTE_CHANGE: 60,
    ReportType.SAFETY: 30,
    ReportType.OTHER: 15,
}

CONFIRM_THRESHOLD = 2
DISMISS_MARGIN = 2
RATE_LIMIT_PER_HOUR = 5
DEDUP_WINDOW_MINUTES = 10


def compute_expires_at(report_type: str, base: datetime) -> datetime:
    ttl = REPORT_TTL_MINUTES.get(report_type, 30)
    return base + timedelta(minutes=ttl)
