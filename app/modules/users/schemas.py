from pydantic import BaseModel

from app.modules.auth.schemas import UserProfileOut

__all__ = ["UserProfileOut", "UserStatsOut"]


class UserStatsOut(BaseModel):
    trips: int
