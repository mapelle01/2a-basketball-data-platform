"""FASE 11 + FASE 13 — HTTP error mapping.

Stable error envelope:

    {"error": {"code": "...", "message": "...", "details": {...}}, "command_id": "..."}

Status policy:
  400 malformed JSON / invalid request envelope
  401 unauthenticated (missing/invalid API key on a protected command)
  403 authenticated but insufficient role for the command
  404 unknown command, missing aggregate, unknown contract
  409 optimistic-concurrency conflict (StaleVersionError / serialization)  -- never hidden
  413 payload too large
  422 contract validation failure / domain validation error
  429 rate limited (in-memory fixed-window limiter)
  503 infrastructure temporarily unavailable
  500 unexpected error (logged; NO stack trace to the client)

Infrastructure errors are NEVER surfaced as DomainErrors and never leak internal
details (SQL, DSN, driver names) to the client.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..domain.common import DomainError
from ..domain.errors import EntityNotFound, MatchNotFound
from ..infrastructure.logging import Logger
from ..infrastructure.persistence.errors import InfrastructureError, StaleVersionError


def _to_code(exc: BaseException) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", exc.__class__.__name__).upper()


def error_response(
    status: int,
    code: str,
    message: str,
    details: Optional[Dict[str, Any]] = None,
    command_id: Optional[str] = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
            },
            "command_id": command_id,
        },
    )


def map_domain_error(exc: DomainError, command_id: Optional[str] = None) -> JSONResponse:
    if isinstance(exc, EntityNotFound):
        return error_response(404, "NOT_FOUND", str(exc) or "entity not found", command_id=command_id)
    return error_response(422, _to_code(exc), str(exc) or "domain validation failed", command_id=command_id)


def register_error_handlers(app, logger: Optional[Logger] = None) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        return error_response(exc.status_code, "HTTP_ERROR", str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        return error_response(
            400,
            "INVALID_BODY",
            "request body is not valid JSON or does not match the expected envelope",
            details={"errors": [str(e) for e in exc.errors()][:5]},
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):
        if logger is not None:
            logger.log("error", "http_request_failed", error=type(exc).__name__)
        return error_response(500, "INTERNAL_ERROR", "unexpected internal error")