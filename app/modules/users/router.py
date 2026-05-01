from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.modules.users.schemas import UserProfileOut, UserStatsOut
from app.modules.users.service import UsersService

router = APIRouter()


@router.get("/me", response_model=UserProfileOut)
def get_me(user: User = Depends(get_current_user)) -> dict:
    return UsersService().me(user)


@router.get("/me/stats", response_model=UserStatsOut)
def get_my_stats(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> dict:
    return UsersService(session).stats(user)
