from sqlalchemy import ForeignKey, Integer, String, Time
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ArrivalSchedule(Base):
    __tablename__ = "arrival_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    route_id: Mapped[str] = mapped_column(ForeignKey("routes.id"), index=True)
    stop_id: Mapped[str] = mapped_column(ForeignKey("stops.id"), index=True)
    weekday: Mapped[int] = mapped_column(Integer, index=True)
    first_service: Mapped[object] = mapped_column(Time())
    last_service: Mapped[object] = mapped_column(Time())
    headway_minutes: Mapped[int] = mapped_column(Integer)
    dest_es: Mapped[str] = mapped_column(String(255))
    dest_en: Mapped[str] = mapped_column(String(255))
    occupancy: Mapped[int] = mapped_column(Integer, default=2)
