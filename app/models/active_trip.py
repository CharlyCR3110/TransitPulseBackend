from datetime import datetime
import uuid
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ActiveTrip(Base):
    __tablename__ = "active_trips"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    active_trip_id: Mapped[str] = mapped_column(
        String(36),
        unique=True,
        index=True,
        default=lambda: str(uuid.uuid4()),
    )
    trip_id: Mapped[str] = mapped_column(ForeignKey("trip_templates.id"), index=True)
    user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    current_step_index: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="in_progress")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ActiveTripStep(Base):
    __tablename__ = "active_trip_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    active_trip_id: Mapped[int] = mapped_column(ForeignKey("active_trips.id"), index=True)
    step_index: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))
    route: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    time_label: Mapped[str] = mapped_column(String(16))
    minutes: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict[str, object]] = mapped_column(JSON)
