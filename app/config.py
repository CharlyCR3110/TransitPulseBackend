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
    boarding_walk_radius_m: float = Field(800.0, alias="BOARDING_WALK_RADIUS_M")
    fuzzy_threshold: float = Field(0.3, alias="FUZZY_THRESHOLD")
    predictions_default_horizon_min: int = Field(
        60, alias="PREDICTIONS_DEFAULT_HORIZON_MIN"
    )
    predictions_max_per_stop: int = Field(10, alias="PREDICTIONS_MAX_PER_STOP")
    predictions_confidence_thresholds: tuple[float, float] = Field(
        (2.0, 5.0),
        alias="PREDICTIONS_CONFIDENCE_THRESHOLDS",
    )
    sentry_dsn: str | None = Field(None, alias="SENTRY_DSN")
    sentry_environment: str = Field("development", alias="SENTRY_ENVIRONMENT")
    sentry_traces_sample_rate: float = Field(0.0, alias="SENTRY_TRACES_SAMPLE_RATE")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
