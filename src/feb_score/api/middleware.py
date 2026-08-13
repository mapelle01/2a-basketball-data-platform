"""FASE 11 + FASE 13 — HTTP middleware.

* ``request_id``: generated when missing (``X-Request-ID`` header) and echoed back;
  every log record emitted during the request carries it.
* Security posture (FASE 13) — each header has a documented reason:
  - ``X-Content-Type-Options: nosniff``: the API never serves browser-renderable
    content; nosniff prevents MIME-sniffing attacks if a resource is ever served.
  - ``X-Frame-Options: DENY``: this is a JSON API, not a page; DENY stops
    clickjacking framing in any embedding context.
  - ``Cache-Control: no-store``: command/read responses carry data that must not be
    cached by intermediaries (idempotency-sensitive, correctness-sensitive).
  - No CORS headers are added: the API has NO browser clients (it is a
    server-to-server / ingest API); enabling CORS would broaden the attack
    surface without a consumer. Add CORS only when a browser client exists.
* ``RateLimitMiddleware``: in-memory fixed-window limiter (FASE 13) protecting the
  command endpoints from abuse. Keyed by the authenticated principal (or client
  IP for anonymous). Returns 429 with ``Retry-After``. Single-process counter by
  design: a multi-instance deployment needs a shared store (documented).
* Request observability: every request is logged with method, path, status,
  duration and request_id — WITHOUT body, headers, credentials or secrets.
"""

from __future__ import annotations

import time
import threading
import uuid
from typing import Callable, Dict, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from ..infrastructure.logging import (
    Logger,
    current_request_id,
    reset_request_id,
    set_request_id,
)

DEFAULT_BODY_LIMIT = 1024 * 1024  # 1 MiB

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Cache-Control": "no-store",
}


class RateLimiter:
    """In-memory fixed-window limiter. Not shared across processes (documented)."""

    def __init__(self, limit: int = 120, window_seconds: int = 60) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: Dict[str, list] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            recent = [t for t in self._hits.get(key, []) if now - t < self.window]
            if len(recent) >= self.limit:
                self._hits[key] = recent
                return False
            recent.append(now)
            self._hits[key] = recent
            return True

    def remaining(self, key: str) -> int:
        now = time.monotonic()
        with self._lock:
            recent = [t for t in self._hits.get(key, []) if now - t < self.window]
            return max(0, self.limit - len(recent))


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Request correlation, security headers, body-limit and request logging."""

    def __init__(
        self,
        app,
        body_size_limit: int = DEFAULT_BODY_LIMIT,
        rate_limiter: Optional[RateLimiter] = None,
    ) -> None:
        super().__init__(app)
        self.body_size_limit = body_size_limit
        self.rate_limiter = rate_limiter

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        token = set_request_id(request_id)
        started = time.monotonic()
        logger: Logger = getattr(request.app.state, "logger", None)

        if self.body_size_limit and request.method in {"POST", "PUT", "PATCH"}:
            declared = request.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > self.body_size_limit:
                self._log(logger, "warning", "http_request_rejected", request_id,
                          method=request.method, path=request.url.path, status=413,
                          reason="payload_too_large")
                reset_request_id(token)
                return self._json(
                    413, "PAYLOAD_TOO_LARGE", f"request body exceeds {self.body_size_limit} bytes"
                )

        if request.method == "POST" and request.url.path.startswith("/v1/commands/"):
            limiter = self.rate_limiter
            if limiter is not None:
                client_key = self._client_key(request)
                if not limiter.allow(client_key):
                    self._log(logger, "warning", "http_request_rejected", request_id,
                              method=request.method, path=request.url.path, status=429,
                              reason="rate_limited")
                    reset_request_id(token)
                    return self._json(
                        429,
                        "RATE_LIMITED",
                        "too many requests; slow down and retry later",
                        extra_headers={"Retry-After": str(limiter.window)},
                    )

        try:
            response = await call_next(request)
        except Exception as exc:  # noqa: BLE001 - keep the error handler in charge
            self._log(logger, "error", "http_request_failed", request_id,
                      method=request.method, path=request.url.path,
                      error=type(exc).__name__, duration_ms=self._elapsed(started))
            raise
        finally:
            reset_request_id(token)

        status = getattr(response, "status_code", 500)
        self._log(logger, "info", "http_request", request_id,
                  method=request.method, path=request.url.path, status=status,
                  duration_ms=self._elapsed(started))
        response.headers["X-Request-ID"] = request_id
        for name, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

    def _client_key(self, request: Request) -> str:
        auth = getattr(request.app.state, "auth", None)
        if auth is not None:
            principal = auth.authenticate(request)
            if principal is not None:
                return f"principal:{principal.id}"
        host = getattr(request.client, "host", "unknown")
        return f"ip:{host}"

    @staticmethod
    def _elapsed(started: float) -> str:
        return f"{int((time.monotonic() - started) * 1000)}ms"

    @staticmethod
    def _log(logger: Optional[Logger], level: str, message: str, request_id: str, **fields) -> None:
        if logger is None:
            return
        logger.log(level, message, request_id=request_id, **fields)

    @staticmethod
    def _json(status: int, code: str, message: str, extra_headers: Optional[dict] = None) -> JSONResponse:
        headers = dict(extra_headers or {})
        headers.update(_SECURITY_HEADERS)
        return JSONResponse(
            status_code=status,
            content={"error": {"code": code, "message": message, "details": {}}, "command_id": None},
            headers=headers,
        )


class RequestLogger(Logger):
    """Decorates a Logger, injecting the active ``request_id`` into every record."""

    def __init__(self, base: Logger) -> None:
        self._base = base

    def log(self, level: str, message: str, **fields) -> None:
        request_id = current_request_id()
        if request_id:
            fields.setdefault("request_id", request_id)
        self._base.log(level, message, **fields)