from fastapi import APIRouter, Depends

from app.dependencies import get_current_user
from app.models.user import User
from app.modules.users.schemas import UserProfileOut
from app.modules.users.service import UsersService

router = APIRouter()


@router.get("/me", response_model=UserProfileOut)
def get_me(user: User = Depends(get_current_user)) -> dict:
    return UsersService().me(user)
