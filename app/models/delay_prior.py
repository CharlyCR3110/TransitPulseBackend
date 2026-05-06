from sqlalchemy import Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class DelayPrior(Base):
    __tablename__ = "delay_priors"

    route_id: Mapped[str] = mapped_column(
        ForeignKey("routes.id", ondelete="CASCADE"), primary_key=True
    )
    direction: Mapped[str] = mapped_column(String(16), primary_key=True)
    hour_of_week: Mapped[int] = mapped_column(Integer, primary_key=True)
    mean_delay_min: Mapped[float] = mapped_column(Float, nullable=False)
    std_delay_min: Mapped[float] = mapped_column(Float, nullable=False)
    n_observations: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
