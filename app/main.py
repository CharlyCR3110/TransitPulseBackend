import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config import get_settings
from app.db import engine
from app.observability import init_observability
from app.modules.alerts.router import router as alerts_router
from app.modules.arrivals.router import router as arrivals_router
from app.modules.auth.router import router as auth_router
from app.modules.health.router import router as health_router
from app.modules.planner.router import router as planner_router
from app.modules.predictions.router import router as predictions_router
from app.modules.reports.router import router as reports_router
from app.modules.routes.router import router as routes_router
from app.modules.shared.exceptions import AppError
from app.modules.shared.logging import add_logging_middleware, configure_logging
from app.modules.stops.router import router as stops_router
from app.modules.users.router import router as users_router


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging()
    init_observability(settings)
    app = FastAPI(title=settings.app_name, version=settings.app_version)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    add_logging_middleware(app)

    @app.on_event("startup")
    def ensure_pg_trgm_extension() -> None:
        with engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))

    @app.on_event("startup")
    def warm_seed_cache() -> None:
        from app.db import SessionLocal
        from app.lib import seed_cache

        with SessionLocal() as session:
            seed_cache.reload(session)

    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details or None,
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Validation error",
                    "details": {"errors": exc.errors()},
                }
            },
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
        logging.getLogger("transitpulse").exception("unhandled_exception", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "Internal server error",
                    "details": None,
                }
            },
        )

    app.include_router(health_router, prefix="/api/v1/health", tags=["health"])
    app.include_router(planner_router, prefix="/api/v1/planner", tags=["planner"])
    app.include_router(stops_router, prefix="/api/v1/stops", tags=["stops"])
    app.include_router(routes_router, prefix="/api/v1/routes", tags=["routes"])
    app.include_router(arrivals_router, prefix="/api/v1/arrivals", tags=["arrivals"])
    app.include_router(predictions_router, prefix="/api/v1/predictions", tags=["predictions"])
    app.include_router(alerts_router, prefix="/api/v1/alerts", tags=["alerts"])
    app.include_router(reports_router, prefix="/api/v1/reports", tags=["reports"])
    app.include_router(auth_router, prefix="/api/v1/auth", tags=["auth"])
    app.include_router(users_router, prefix="/api/v1/users", tags=["users"])
    return app


app = create_app()
