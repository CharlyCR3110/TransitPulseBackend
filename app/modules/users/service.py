from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.active_trip import ActiveTrip
from app.models.user import User


class UsersService:
    def __init__(self, session: Session | None = None):
        self.session = session

    def me(self, user: User) -> dict:
        return {
            "id": user.id,
            "email": user.email,
            "displayName": user.display_name,
            "reputationScore": user.reputation_score,
            "createdAt": user.created_at.isoformat(),
        }

    def stats(self, user: User) -> dict:
        if self.session is None:
            raise RuntimeError("UsersService.stats requires a session")
        trips = self.session.scalar(
            select(func.count())
            .select_from(ActiveTrip)
            .where(ActiveTrip.user_id == user.id)
        )
        return {"trips": int(trips or 0)}
