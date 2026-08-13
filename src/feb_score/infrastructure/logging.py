"""Observability: a minimal, pluggable Logger abstraction.

The domain/application layers never log; the infrastructure layer (this module,
the dispatcher and the CommandRunner) emits structured lifecycle events:

* ``command_started`` / ``command_completed`` / ``command_failed``
* ``event_published`` / ``dispatch_failed``

A concrete backend can be swapped (JSON file, external platform) by implementing
``Logger``; the default ``StdLogger`` writes to Python's ``logging`` with
``key=value`` fields, so tests can also inject a ``RecordingLogger``.

Request correlation: the HTTP middleware publishes the active ``request_id``
into a contextvar (``set_request_id``/``reset_request_id``) so that the runner
and the dispatcher — running inside the request context — tag every record with
the same ``request_id`` that correlates HTTP request -> command_id -> events.
"""

from __future__ import annotations

import contextvars
import logging
import sys
from typing import Any, Dict, List, Optional, Tuple

VALID_LEVELS = ("debug", "info", "warning", "error", "critical")

_request_id: contextvars.ContextVar = contextvars.ContextVar("feb_request_id", default=None)


def set_request_id(value: str) -> contextvars.Token:
    """Bind ``value`` to the current execution context. Returns a reset token."""
    return _request_id.set(value)


def reset_request_id(token: contextvars.Token) -> None:
    _request_id.reset(token)


def current_request_id() -> Optional[str]:
    """The request_id in scope, or None outside any HTTP request."""
    return _request_id.get()


class Logger:
    """Structured-logging port. Implementations must be safe to call from any thread."""

    def log(self, level: str, message: str, **fields: Any) -> None:
        raise NotImplementedError


class StdLogger(Logger):
    """Default backend: Python ``logging`` with ``key=value`` fields appended."""

    def __init__(self, name: str = "feb_score", level: str = "info") -> None:
        if level not in VALID_LEVELS:
            raise ValueError(f"invalid log level: {level!r}")
        self._logger = logging.getLogger(name)
        self._logger.setLevel(getattr(logging, level.upper()))
        if not self._logger.handlers:
            handler = logging.StreamHandler(sys.stderr)
            handler.setFormatter(
                logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
            )
            self._logger.addHandler(handler)
        self._logger.propagate = False

    def log(self, level: str, message: str, **fields: Any) -> None:
        if level not in VALID_LEVELS:
            raise ValueError(f"invalid log level: {level!r}")
        suffix = " ".join(f"{k}={v}" for k, v in sorted(fields.items()) if v is not None)
        text = f"{message} {suffix}".rstrip()
        getattr(self._logger, level)(text)


class RecordingLogger(Logger):
    """Test double: captures (level, message, fields) for assertions."""

    def __init__(self) -> None:
        self.records: List[Tuple[str, str, Dict[str, Any]]] = []

    def log(self, level: str, message: str, **fields: Any) -> None:
        self.records.append((level, message, dict(fields)))

    def messages(self, *names: str) -> List[Tuple[str, str, Dict[str, Any]]]:
        if not names:
            return self.records
        return [r for r in self.records if r[1] in names]

    def has(self, name: str, level: Optional[str] = None) -> bool:
        return any(
            r[1] == name and (level is None or r[0] == level) for r in self.records
        )