"""Application entrypoint: CommandRunner.

The single boundary through which EXTERNAL callers (CLI, API, worker) invoke the
system. Responsibilities:

1. Open ONE transaction (``SqliteUnitOfWork``): aggregate change + its events are
   atomic (state/events/idempotency commit together, or none do).
2. Log a traceable lifecycle (``command_started`` / ``command_completed`` /
   ``command_failed``) via the Logger abstraction.
3. After commit, dispatch events at-least-once (if a dispatcher is configured).

Domain/Application remain SQLite-free: the runner lives in infrastructure and the
handlers it calls are plain objects implementing ``handle(command)``.
"""

from __future__ import annotations

from typing import Any, List, Optional

from .logging import Logger, StdLogger, current_request_id
from .persistence.connection import SqliteDatabase
from .persistence.event_dispatcher import SyncEventDispatcher


def as_event_list(result: Any) -> List[object]:
    """Normalize a handler result (list of events | single event | None) to a list."""
    if result is None:
        return []
    if isinstance(result, list):
        return [e for e in result if e is not None]
    return [result]


class CommandRunner:
    def __init__(
        self,
        db: SqliteDatabase,
        dispatcher: Optional[SyncEventDispatcher] = None,
        logger: Optional[Logger] = None,
    ) -> None:
        self.db = db
        self.dispatcher = dispatcher
        self.logger = logger or StdLogger("feb_score.runner")

    def run(self, handler: Any, command: Any) -> Any:
        command_name = command.__class__.__name__
        request_id = current_request_id()
        self.logger.log(
            "info",
            "command_started",
            command=command_name,
            command_id=getattr(command, "command_id", None),
            request_id=request_id,
        )
        try:
            with self.db.unit_of_work() as uow:
                result = handler.handle(command)
                events = as_event_list(result)
                uow.append_events(events)
            self.logger.log(
                "info",
                "command_completed",
                command=command_name,
                command_id=getattr(command, "command_id", None),
                events=len(events),
                request_id=request_id,
            )
        except Exception as exc:
            self.logger.log(
                "error",
                "command_failed",
                command=command_name,
                command_id=getattr(command, "command_id", None),
                error=type(exc).__name__,
                request_id=request_id,
            )
            raise
        if self.dispatcher is not None:
            delivered = self.dispatcher.dispatch()
            self.logger.log(
                "info",
                "dispatch_completed",
                command=command_name,
                command_id=getattr(command, "command_id", None),
                delivered=delivered,
                request_id=request_id,
            )
        return result