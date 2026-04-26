from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db import get_session
from app.models.user import User
from app.modules.shared.exceptions import AuthRequiredError
from app.modules.shared.security import decode_access_token

bearer_scheme = HTTPBearer(auto_error=False)


def get_db(session: Annotated[Session, Depends(get_session)]) -> Session:
    return session


def get_current_user_optional(
    session: Annotated[Session, Depends(get_db)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User | None:
    if credentials is None:
        return None
    payload = decode_access_token(credentials.credentials)
    user = session.get(User, payload["sub"])
    if user is None or not user.is_active:
        raise AuthRequiredError("Authentication required")
    return user


def get_current_user(
    user: Annotated[User | None, Depends(get_current_user_optional)],
) -> User:
    if user is None:
        raise AuthRequiredError("Authentication required")
    return user
