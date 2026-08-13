"""Simple synchronous event dispatch with at-least-once delivery.

No external infrastructure: a publisher abstraction + a test consumer. Events are
marked ``delivered`` ONLY after the publisher returns successfully; a failed
publish keeps the event pending so a later retry can deliver it. A consumer that
receives an event twice must be idempotent (at-least-once semantics).

Failures (publisher error or an unprocessable/corrupt event row) are logged as
``dispatch_failed`` with the event_id, event_type, error classification and the
correlating request_id; dispatch stops and the event stays pending for retry.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from ...domain.events import DomainEvent
from ..logging import Logger, StdLogger, current_request_id
from .event_catalog import aggregate_ref
from .event_store import reconstruct_event


class EventPublisher(ABC):
    """Abstraction over the delivery mechanism. Implementations raise on failure."""

    @abstractmethod
    def publish(self, event: DomainEvent) -> None:
        pass


class SyncEventDispatcher:
    """Dispatch pending outbox events through any ``db`` exposing ``event_store()``.

    Works against both the SQLite and the PostgreSQL infrastructure: the store
    provides ``fetch_undelivered`` / ``mark_delivered`` / ``pending_count`` and the
    shared ``reconstruct_event`` rebuilds the ``DomainEvent`` from its row.
    """

    def __init__(
        self,
        db,
        publisher: EventPublisher,
        logger: Optional[Logger] = None,
    ) -> None:
        self.db = db
        self.publisher = publisher
        self.logger = logger or StdLogger("feb_score.dispatcher")
        self._store = db.event_store()

    def dispatch(self, limit: int = 100) -> int:
        """Publish pending events; mark each delivered only after success.

        Returns the number of events successfully delivered. On the first failure
        (publisher error or a corrupt/unprocessable event row) dispatch stops and
        leaves the event pending for retry.
        """
        delivered = 0
        request_id = current_request_id()
        for row in self._store.fetch_undelivered(limit):
            try:
                event = reconstruct_event(row)
                self.publisher.publish(event)
            except Exception as exc:
                self.logger.log(
                    "error",
                    "dispatch_failed",
                    event_id=row["event_id"],
                    event_type=row["event_type"],
                    error=type(exc).__name__,
                    error_message=str(exc),
                    request_id=request_id,
                )
                break
            self._store.mark_delivered(row["event_id"])
            self.logger.log(
                "info",
                "event_published",
                event_id=row["event_id"],
                event_type=row["event_type"],
                request_id=request_id,
            )
            delivered += 1
        return delivered

    def pending_count(self) -> int:
        return self._store.pending_count()


class IdempotentConsumer(EventPublisher):
    """Dedupes deliveries so a consumer is safe under at-least-once semantics.

    A crash between a successful publish and the delivered-mark leaves the event
    pending and it will be redelivered; wrapping the consumer in this class
    guarantees the downstream publisher sees each event exactly once.
    """

    def __init__(self, publisher: EventPublisher) -> None:
        self.publisher = publisher
        self._seen = set()

    def publish(self, event: DomainEvent) -> None:
        if event.event_id in self._seen:
            return
        self.publisher.publish(event)
        self._seen.add(event.event_id)


class RecordingPublisher(EventPublisher):
    """Test consumer: collects published events and can fail on demand."""

    def __init__(self, fail_on: int = None) -> None:
        self.published: List[DomainEvent] = []
        self.fail_on = fail_on

    def publish(self, event: DomainEvent) -> None:
        if self.fail_on is not None and len(self.published) == self.fail_on:
            raise RuntimeError(f"Injected publish failure before {type(event).__name__}")
        self.published.append(event)


class LoggingPublisher(EventPublisher):
    """Production default (no external broker yet): "publishes" by logging the
    event and marking it delivered. Keeps outbox semantics (delivered only after a
    successful publish) and gives a clear seam to swap in a real transport later."""

    def __init__(self, logger: Optional[Logger] = None) -> None:
        self.logger = logger or StdLogger("feb_score.publisher")

    def publish(self, event: DomainEvent) -> None:
        self.logger.log(
            "info",
            "event_published",
            event_id=event.event_id,
            event_type=type(event).__name__,
            aggregate=aggregate_ref(event)[0],
            aggregate_id=aggregate_ref(event)[1],
            request_id=current_request_id(),
        )