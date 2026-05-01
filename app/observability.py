from __future__ import annotations

import logging

from app.config import Settings

logger = logging.getLogger("transitpulse")


def init_observability(settings: Settings) -> None:
    if not settings.sentry_dsn:
        logger.info("sentry_disabled", extra={"reason": "no_dsn"})
        return

    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.sentry_environment,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        send_default_pii=False,
        integrations=[
            StarletteIntegration(),
            FastApiIntegration(),
        ],
    )
    logger.info(
        "sentry_initialized",
        extra={"environment": settings.sentry_environment},
    )
