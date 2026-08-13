"""psycopg error translation into the infrastructure taxonomy (FASE 12)."""

from __future__ import annotations

import psycopg

from ..errors import (
    ConstraintViolationError,
    DatabaseUnavailableError,
    DeadlockError,
    InfrastructureError,
    SerializationConflictError,
)


def translate_pg_error(exc: Exception) -> InfrastructureError:
    """Classify a psycopg error into the infrastructure taxonomy.

    The API maps ``StaleVersionError``/``SerializationConflictError`` to HTTP 409
    (retry), and any other ``InfrastructureError`` to HTTP 503. This keeps
    database-specific failures out of the generic 500 path.
    """
    if isinstance(exc, psycopg.errors.SerializationFailure):
        return SerializationConflictError(f"serialization failure: {exc}")
    if isinstance(exc, psycopg.errors.DeadlockDetected):
        return DeadlockError(f"deadlock detected: {exc}")
    if isinstance(exc, psycopg.errors.IntegrityError):
        return ConstraintViolationError(f"constraint violation: {exc}")
    if isinstance(exc, (psycopg.OperationalError, psycopg.InterfaceError)):
        return DatabaseUnavailableError(f"database unavailable: {exc}")
    if isinstance(exc, InfrastructureError):
        return exc
    return InfrastructureError(str(exc))