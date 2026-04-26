from app.models.user import User


class UsersService:
    def me(self, user: User) -> dict:
        return {
            "id": user.id,
            "email": user.email,
            "displayName": user.display_name,
            "reputationScore": user.reputation_score,
            "createdAt": user.created_at.isoformat(),
        }
