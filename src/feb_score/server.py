"""FASE 13 — Production entrypoint (composition root).

Wires the real system from the environment and runs Uvicorn:

    1. read + validate Settings (fails fast on invalid/missing production config);
    2. build the database (PostgreSQL when FEB_SCORE_DATABASE_URL is set, else
       SQLite), apply migrations;
    3. build the CommandGateway with a production dispatcher (outbox drains after
       every committed command via LoggingPublisher — no external broker yet);
    4. build the AuthenticationProvider from FEB_SCORE_API_KEYS (never from code);
    5. build the app with rate limiting and serve.

Graceful shutdown (FASE 13): Uvicorn handles SIGTERM by stopping the event loop,
finishing in-flight requests and running the lifespan shutdown. feb_score keeps
NO persistent connections or pools (every connection is closed in a ``finally``)
and NO background workers (the dispatcher runs inline after each COMMIT), so a
shutdown cannot drop transactions or leave connections open.
"""

from __future__ import annotations

import os
from typing import Optional

import uvicorn

from .api.auth import ApiKeyAuthenticationProvider
from .api.main import create_app
from .api.middleware import RateLimiter
from .infrastructure.config import ConfigurationError, Settings, settings_from_env
from .infrastructure.logging import StdLogger
from .infrastructure.persistence.event_dispatcher import LoggingPublisher, SyncEventDispatcher
from .infrastructure.wiring import build_gateway

HOST = os.environ.get("FEB_SCORE_HOST", "0.0.0.0")


def _port() -> int:
    """FASE 15 §4: parse FEB_SCORE_PORT lazily so a malformed value surfaces
    as ConfigurationError at boot, never a bare ValueError at import time.

    FASE 18.1: fall back to the standard ``PORT`` variable (injected by
    container platforms such as Railway) when FEB_SCORE_PORT is unset. The
    explicit FEB_SCORE_PORT always wins; the error message names both."""
    raw = os.environ.get("FEB_SCORE_PORT") or os.environ.get("PORT") or "8000"
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ConfigurationError(
            f"FEB_SCORE_PORT/PORT must be an integer, got {raw!r}"
        ) from None


def _build_db(settings: Settings):
    if settings.database_url:
        from .infrastructure.persistence.postgres.connection import PgDatabase

        db = PgDatabase(settings.database_url, settings=settings)
        db.migrate()
        return db
    from .infrastructure.persistence.connection import SqliteDatabase

    db = SqliteDatabase(settings.db_path, settings=settings)
    db.migrate()
    return db


def build_production_app(settings: Optional[Settings] = None):
    """Assemble the application boundary (used by both the server and tests)."""
    settings = settings or settings_from_env()
    settings.validate()

    logger = StdLogger("feb_score", level=settings.log_level)
    db = _build_db(settings)
    dispatcher = SyncEventDispatcher(
        db, LoggingPublisher(logger=logger), logger=logger
    )
    gateway = build_gateway(db, dispatcher=dispatcher, logger=logger)
    auth = ApiKeyAuthenticationProvider.from_env(settings.api_keys)
    rate_limiter = (
        RateLimiter(limit=settings.rate_limit_per_minute)
        if settings.rate_limit_enabled
        else None
    )
    return create_app(gateway, auth=auth, logger=logger, rate_limiter=rate_limiter)


def main() -> None:
    settings = settings_from_env()
    settings.validate()
    app = build_production_app(settings)
    uvicorn.run(app, host=HOST, port=_port(), log_level=settings.log_level)


if __name__ == "__main__":
    main()