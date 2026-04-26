from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url,
    pool_size=1,
    max_overflow=1,
    pool_pre_ping=True,
    pool_recycle=600,
)

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
Base = declarative_base()


def get_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
