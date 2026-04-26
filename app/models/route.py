from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Route(Base):
    __tablename__ = "routes"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    short_name: Mapped[str] = mapped_column(String(32))
    long_name: Mapped[str] = mapped_column(String(255), index=True)
    mode: Mapped[str] = mapped_column(String(16), default="bus")
    fare_min: Mapped[int] = mapped_column(Integer)
    fare_max: Mapped[int] = mapped_column(Integer)
    color: Mapped[str] = mapped_column(String(16))


class RouteStop(Base):
    __tablename__ = "route_stops"

    route_id: Mapped[str] = mapped_column(ForeignKey("routes.id"), primary_key=True)
    stop_id: Mapped[str] = mapped_column(ForeignKey("stops.id"), primary_key=True)
    stop_order: Mapped[int] = mapped_column(Integer)
    segment_minutes: Mapped[int] = mapped_column(Integer, default=3)
