from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    app_name: str = "TransitPulse Backend"
    app_version: str = "1.0.0"
    database_url: str = Field(
        "postgresql+psycopg://transitpulse:transitpulse@localhost:5432/transitpulse",
        alias="DATABASE_URL",
    )
    jwt_secret: str = Field(
        "dev-only-secret-change-me-32-bytes-min",
        alias="JWT_SECRET",
        min_length=32,
    )
    jwt_expires_seconds: int = Field(86400, alias="JWT_EXPIRES_SECONDS")
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"],
        alias="CORS_ORIGINS",
    )
    log_level: str = Field("INFO", alias="LOG_LEVEL")
    arrivals_home_limit: int = Field(6, alias="ARRIVALS_HOME_LIMIT")
    nearest_stop_radius_m: float = Field(2000.0, alias="NEAREST_STOP_RADIUS_M")
    fuzzy_threshold: float = Field(0.3, alias="FUZZY_THRESHOLD")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
