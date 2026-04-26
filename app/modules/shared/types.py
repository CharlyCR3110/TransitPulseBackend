from enum import StrEnum


class SortMode(StrEnum):
    FASTEST = "fastest"
    CHEAPEST = "cheapest"
    FEWEST = "fewest"


class ActiveTripStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ABANDONED = "abandoned"


class ReportType(StrEnum):
    DELAY = "delay"
    BREAKDOWN = "breakdown"
    ACCIDENT = "accident"
    OVERCROWDING = "overcrowding"
    ROUTE_CHANGE = "route_change"
    SAFETY = "safety"
    OTHER = "other"


class ReportStatus(StrEnum):
    NEW = "new"
    CONFIRMED = "confirmed"
    DISMISSED = "dismissed"
    RESOLVED = "resolved"
