from datetime import datetime
import uuid

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class TripTemplate(Base):
    __tablename__ = "trip_templates"

    id: Mapped[str] = mapped_column(
        String(32),
        primary_key=True,
        default=lambda: f"tt_{uuid.uuid4().hex[:10]}",
    )
    origin_stop_id: Mapped[str] = mapped_column(ForeignKey("stops.id"))
    destination_stop_id: Mapped[str] = mapped_column(ForeignKey("stops.id"))
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    total_minutes: Mapped[int] = mapped_column(Integer)
    total_price: Mapped[int] = mapped_column(Integer)
    transfers: Mapped[int] = mapped_column(Integer)
    walk_min: Mapped[int] = mapped_column(Integer)
    leave_in: Mapped[int] = mapped_column(Integer)
    steps: Mapped[list[dict[str, object]]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
