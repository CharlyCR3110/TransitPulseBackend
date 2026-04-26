from sqlalchemy import text
from sqlalchemy.orm import Session


class HealthService:
    def __init__(self, session: Session):
        self.session = session

    def check(self) -> dict[str, str]:
        self.session.execute(text("SELECT 1"))
        return {"status": "ok"}
