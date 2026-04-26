from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Stop(Base):
    __tablename__ = "stops"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name_key: Mapped[str] = mapped_column(String(64), index=True)
    addr_key: Mapped[str] = mapped_column(String(64))
    label_es: Mapped[str] = mapped_column(String(255))
    label_en: Mapped[str] = mapped_column(String(255))
    addr_es: Mapped[str] = mapped_column(String(255))
    addr_en: Mapped[str] = mapped_column(String(255))
    lat: Mapped[float] = mapped_column()
    lng: Mapped[float] = mapped_column()
    live: Mapped[bool] = mapped_column(Boolean, default=True)
