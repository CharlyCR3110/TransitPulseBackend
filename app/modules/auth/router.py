from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.modules.auth.schemas import LoginIn, RegisterIn, TokenOut, UserProfileOut
from app.modules.auth.service import AuthService

router = APIRouter()


@router.post("/register", response_model=UserProfileOut, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterIn, session: Session = Depends(get_db)) -> dict:
    return AuthService(session).register(payload.model_dump())


@router.post("/login", response_model=TokenOut)
def login(payload: LoginIn, session: Session = Depends(get_db)) -> dict:
    return AuthService(session).login(payload.model_dump())
