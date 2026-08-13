"""Outbox-lite: persistent DomainEvent log written in the command transaction."""

from __future__ import annotations

import json
import sqlite3
from typing import List

from ...domain.events import DomainEvent
from .connection import SqliteDatabase, active_connection
from .event_catalog import (
    EVENT_TYPES,
    _json_safe_event,
    aggregate_ref,
    datetime_from_iso,
    reconstruct_event,
)

__all__ = [
    "EVENT_TYPES",
    "SqliteEventStore",
    "aggregate_ref",
    "datetime_from_iso",
    "reconstruct_event",
]


class SqliteEventStore:
    """Persists events inside the active transaction (outbox-lite).

    Outside a unit of work each call uses its own connection (autocommit).
    """

    def __init__(self, db: SqliteDatabase) -> None:
        self.db = db

    def _conn(self) -> tuple:
        active = active_connection()
        if active is not None:
            return active, False
        return self.db.connect(), True

    def append_many(self, events: List[DomainEvent]) -> None:
        conn, owned = self._conn()
        try:
            conn.executemany(
                "INSERT OR IGNORE INTO domain_events"
                " (event_id, event_type, aggregate_type, aggregate_id, produced_at, payload, delivered)"
                " VALUES (?, ?, ?, ?, ?, ?, 0)",
                [
                    (
                        event.event_id,
                        type(event).__name__,
                        aggregate_ref(event)[0],
                        aggregate_ref(event)[1],
                        event.meta.produced_at.isoformat(),
                        json.dumps(_json_safe_event(event)),
                    )
                    for event in events
                ],
            )
        finally:
            if owned:
                conn.close()

    def fetch_undelivered(self, limit: int = 100) -> List[sqlite3.Row]:
        conn, owned = self._conn()
        try:
            rows = conn.execute(
                "SELECT event_id, event_type, payload FROM domain_events"
                " WHERE delivered = 0 ORDER BY produced_at, event_id LIMIT ?",
                (limit,),
            ).fetchall()
            return list(rows)
        finally:
            if owned:
                conn.close()

    def mark_delivered(self, event_id: str) -> None:
        conn, owned = self._conn()
        try:
            conn.execute("UPDATE domain_events SET delivered = 1 WHERE event_id = ?", (event_id,))
        finally:
            if owned:
                conn.close()

    def pending_count(self) -> int:
        conn, owned = self._conn()
        try:
            row = conn.execute("SELECT COUNT(*) AS n FROM domain_events WHERE delivered = 0").fetchone()
            return int(row["n"])
        finally:
            if owned:
                conn.close()