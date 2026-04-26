from typing import Literal

from pydantic import BaseModel


class AlertOut(BaseModel):
    id: str
    severity: Literal["bad", "warn", "ok"]
    titleKey: str
    bodyKey: str
    emittedAt: str
    routes: list[str]
