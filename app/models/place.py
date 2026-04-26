from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Place(Base):
    __tablename__ = "places"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    label_es: Mapped[str] = mapped_column(String(255), index=True)
    label_en: Mapped[str] = mapped_column(String(255), index=True)
    near_stop_id: Mapped[str] = mapped_column(ForeignKey("stops.id"))
