from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (
        Index("ix_reports_route_dir_expires", "route_id", "direction", "expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)
    route_id: Mapped[Optional[str]] = mapped_column(ForeignKey("routes.id"), nullable=True)
    stop_id: Mapped[Optional[str]] = mapped_column(ForeignKey("stops.id"), nullable=True)
    active_trip_id: Mapped[Optional[int]] = mapped_column(ForeignKey("active_trips.id"), nullable=True)
    direction: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    type: Mapped[str] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="new")
    confirm_count: Mapped[int] = mapped_column(Integer, default=0)
    deny_count: Mapped[int] = mapped_column(Integer, default=0)
    source_ip: Mapped[Optional[str]] = mapped_column(INET, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
