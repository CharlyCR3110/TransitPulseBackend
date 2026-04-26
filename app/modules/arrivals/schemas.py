from typing import Literal

from pydantic import BaseModel


class ArrivalOut(BaseModel):
    id: str
    route: str
    kind: Literal["bus", "train"]
    destEs: str
    destEn: str
    etaSec: int
    status: str
    occupancy: int
    note_es: str | None = None
    note_en: str | None = None
