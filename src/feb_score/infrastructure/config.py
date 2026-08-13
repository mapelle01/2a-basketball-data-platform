"""FASE 10 + FASE 12 + FASE 13 — Configuration: explicit, injectable,
environment-overridable, validated.

Config policy:
* The ONLY critical parameters are the database path (SQLite) or DSN
  (PostgreSQL). They are INJECTED via ``SqliteDatabase(path)`` /
  ``PgDatabase(dsn)``; never hardcoded inside handlers/repositories.
* No secrets are committed: credentials come from the ``FEB_SCORE_DATABASE_URL``
  and ``FEB_SCORE_API_KEYS`` environment variables, never from source.
* ``build_gateway()`` selects the backend from configuration: a set
  ``FEB_SCORE_DATABASE_URL`` activates the PostgreSQL infrastructure, otherwise
  SQLite is used.
* Environments are separated via ``FEB_SCORE_ENV`` (development / test /
  production). Production config is validated at startup: it must point at a
  real PostgreSQL DSN and define API keys; it never falls back to SQLite.
* ``validate()`` fails fast on invalid values (bad log level, bad ints, missing
  production values) so configuration errors surface at boot, not at runtime.
* No secret is ever logged: the log level / env values are safe, and the API keys
  and database URL are never written to logs.
* Timestamps: the domain deliberately uses timezone-naive UTC
  (``datetime.utcnow``) — a single, documented convention; no timezone parsing
  happens inside handlers.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigurationError(ValueError):
    """Invalid or incomplete configuration (surfaced at startup)."""


def _env_int(name: str, default: int) -> int:
    """Read an integer env var, failing fast with the variable name on bad input."""
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ConfigurationError(f"{name} must be an integer, got {raw!r}") from None


VALID_ENVIRONMENTS = ("development", "test", "production")
VALID_LOG_LEVELS = ("debug", "info", "warning", "error", "critical")


@dataclass(frozen=True)
class Settings:
    # Convenience default for entrypoints; SqliteDatabase(path) remains the source
    # of truth wherever an explicit path is passed.
    db_path: str = os.environ.get("FEB_SCORE_DB", "feb_score.db")
    # PostgreSQL DSN (FASE 12). When set, build_gateway() uses the PostgreSQL
    # infrastructure; when empty, SQLite is used. Credentials come from env.
    database_url: str = os.environ.get("FEB_SCORE_DATABASE_URL", "")
    # Deployment environment (development / test / production).
    env: str = os.environ.get("FEB_SCORE_ENV", "development")
    # Log verbosity for infrastructure logging (StdLogger).
    log_level: str = os.environ.get("FEB_SCORE_LOG_LEVEL", "info")
    # API keys for the ApiKeyAuthenticationProvider (FASE 13). Format
    # "key=principal_id:role;..." — read from env, never logged.
    api_keys: str = os.environ.get("FEB_SCORE_API_KEYS", "")
    # sqlite3.connect() busy timeout: wait this long for a contended write lock
    # before raising "database is locked".
    busy_timeout_ms: int = 5000
    # WAL: concurrent readers during writes (single-writer model).
    wal: bool = True
    # Foreign keys: kept ON for future normalized relationships (matches currently
    # reference external IDs that may legitimately not exist yet, so no FKs are
    # declared — see docs/ARCHITECTURE.md).
    foreign_keys: bool = True
    # Outbox dispatch batch size (events per pass).
    dispatch_batch_size: int = 100
    # Domain timestamp convention (tz-naive UTC).
    timezone: str = "UTC"
    # PostgreSQL connection/statement timeouts (ms) — FASE 13 hardening.
    pg_connect_timeout_ms: int = 5000
    pg_statement_timeout_ms: int = 30000
    # In-memory rate limiting (FASE 13). Enabled in production by default; a
    # single-process counter, not a shared store.
    rate_limit_enabled: bool = os.environ.get("FEB_SCORE_RATE_LIMIT", "true").lower() in {"1", "true", "yes"}
    # FASE 15 §4: static default — env is read only via settings_from_env()
    # (_env_int) so a malformed value surfaces as ConfigurationError at boot,
    # never as a bare ValueError at import time.
    rate_limit_per_minute: int = 120

    def validate(self) -> None:
        """Fail fast on invalid configuration. Safe to call at boot."""
        if self.env not in VALID_ENVIRONMENTS:
            raise ConfigurationError(
                f"invalid FEB_SCORE_ENV {self.env!r}; must be one of {VALID_ENVIRONMENTS}"
            )
        if self.log_level not in VALID_LOG_LEVELS:
            raise ConfigurationError(
                f"invalid FEB_SCORE_LOG_LEVEL {self.log_level!r}; must be one of {VALID_LOG_LEVELS}"
            )
        if self.busy_timeout_ms <= 0:
            raise ConfigurationError("FEB_SCORE_BUSY_TIMEOUT must be > 0")
        if self.dispatch_batch_size <= 0:
            raise ConfigurationError("FEB_SCORE_DISPATCH_BATCH must be > 0")
        if self.pg_connect_timeout_ms <= 0 or self.pg_statement_timeout_ms <= 0:
            raise ConfigurationError("PostgreSQL timeouts must be > 0")
        if self.rate_limit_per_minute <= 0:
            raise ConfigurationError("FEB_SCORE_RATE_LIMIT_PER_MINUTE must be > 0")

        if self.env == "production":
            # Production never runs on SQLite and never without credentials.
            if not self.database_url:
                raise ConfigurationError(
                    "FEB_SCORE_DATABASE_URL is required in production (SQLite is not a "
                    "production backend)"
                )
            if not self.api_keys:
                raise ConfigurationError(
                    "FEB_SCORE_API_KEYS is required in production (no API key => no "
                    "authenticated caller)"
                )


def settings_from_env() -> Settings:
    """Build Settings honoring the documented environment overrides."""
    return Settings(
        db_path=os.environ.get("FEB_SCORE_DB", Settings.db_path),
        database_url=os.environ.get("FEB_SCORE_DATABASE_URL", ""),
        env=os.environ.get("FEB_SCORE_ENV", "development"),
        log_level=os.environ.get("FEB_SCORE_LOG_LEVEL", "info"),
        api_keys=os.environ.get("FEB_SCORE_API_KEYS", ""),
        busy_timeout_ms=_env_int("FEB_SCORE_BUSY_TIMEOUT", 5000),
        dispatch_batch_size=_env_int("FEB_SCORE_DISPATCH_BATCH", 100),
        pg_connect_timeout_ms=_env_int("FEB_SCORE_PG_CONNECT_TIMEOUT", 5000),
        pg_statement_timeout_ms=_env_int("FEB_SCORE_PG_STATEMENT_TIMEOUT", 30000),
        rate_limit_enabled=os.environ.get("FEB_SCORE_RATE_LIMIT", "true").lower() in {"1", "true", "yes"},
        rate_limit_per_minute=_env_int("FEB_SCORE_RATE_LIMIT_PER_MINUTE", 120),
    )