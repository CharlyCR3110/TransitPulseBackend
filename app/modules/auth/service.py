from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User
from app.modules.shared.exceptions import AuthRequiredError, ConflictError
from app.modules.shared.security import create_access_token, hash_password, verify_password


class AuthService:
    def __init__(self, session: Session):
        self.session = session

    def register(self, payload: dict) -> dict:
        email = payload["email"].lower()
        existing = self.session.scalar(select(User).where(User.email == email))
        if existing is not None:
            raise ConflictError("Email already registered", {"email": email})

        user = User(
            email=email,
            password_hash=hash_password(payload["password"]),
            display_name=payload["displayName"],
        )
        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)
        return self._user_out(user)

    def login(self, payload: dict) -> dict:
        email = payload["email"].lower()
        user = self.session.scalar(select(User).where(User.email == email))
        if user is None or not verify_password(payload["password"], user.password_hash):
            raise AuthRequiredError("Invalid email or password")
        token, expires_at = create_access_token(user.id, user.email)
        return {"accessToken": token, "expiresAt": expires_at.isoformat()}

    def _user_out(self, user: User) -> dict:
        return {
            "id": user.id,
            "email": user.email,
            "displayName": user.display_name,
            "reputationScore": user.reputation_score,
            "createdAt": user.created_at.isoformat(),
        }
