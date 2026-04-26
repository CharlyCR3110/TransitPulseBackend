from pydantic import BaseModel, EmailStr, Field


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    displayName: str = Field(min_length=1, max_length=64)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserProfileOut(BaseModel):
    id: str
    email: EmailStr
    displayName: str
    reputationScore: int
    createdAt: str


class TokenOut(BaseModel):
    accessToken: str
    expiresAt: str
