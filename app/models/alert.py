from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    severity: Mapped[str] = mapped_column(String(16))
    title_key: Mapped[str] = mapped_column(String(64))
    body_key: Mapped[str] = mapped_column(String(64))
    emitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class AlertRoute(Base):
    __tablename__ = "alert_routes"

    alert_id: Mapped[str] = mapped_column(ForeignKey("alerts.id"), primary_key=True)
    route_id: Mapped[str] = mapped_column(ForeignKey("routes.id"), primary_key=True)
