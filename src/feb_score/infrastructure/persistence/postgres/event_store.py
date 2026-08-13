"""PostgreSQL outbox store (FASE 12) — same contract as ``SqliteEventStore``.

Events are persisted inside the active transaction (via ``PgUnitOfWork``), payload
is JSONB, ``delivered`` is a boolean. Rows are fetched with ``payload::text`` so
the shared ``reconstruct_event`` (which expects JSON text) works unchanged.
"""

from __future__ import annotations

import json
from typing import List

from ....domain.events import DomainEvent
from .connection import PgDatabase, pg_active_connection
from ..event_catalog import _json_safe_event, aggregate_ref, reconstruct_event


class PgEventStore:
    def __init__(self, db: PgDatabase) -> None:
        self.db = db

    def _conn(self) -> tuple:
        active = pg_active_connection()
        if active is not None:
            return active, False
        return self.db.connect(), True

    def append_many(self, events: List[DomainEvent]) -> None:
        conn, owned = self._conn()
        try:
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO domain_events"
                    " (event_id, event_type, aggregate_type, aggregate_id, produced_at, payload, delivered)"
                    " VALUES (%s, %s, %s, %s, %s, %s::jsonb, FALSE)"
                    " ON CONFLICT (event_id) DO NOTHING",
                    [
                        (
                            event.event_id,
                            type(event).__name__,
                            aggregate_ref(event)[0],
                            aggregate_ref(event)[1],
                            event.meta.produced_at,
                            json.dumps(_json_safe_event(event)),
                        )
                        for event in events
                    ],
                )
        finally:
            if owned:
                conn.close()

    def fetch_undelivered(self, limit: int = 100) -> List[dict]:
        conn, owned = self._conn()
        try:
            return list(
                conn.execute(
                    "SELECT event_id, event_type, payload::text AS payload FROM domain_events"
                    " WHERE delivered = FALSE ORDER BY produced_at, event_id LIMIT %s",
                    (limit,),
                ).fetchall()
            )
        finally:
            if owned:
                conn.close()

    def mark_delivered(self, event_id: str) -> None:
        conn, owned = self._conn()
        try:
            conn.execute("UPDATE domain_events SET delivered = TRUE WHERE event_id = %s", (event_id,))
        finally:
            if owned:
                conn.close()

    def pending_count(self) -> int:
        conn, owned = self._conn()
        try:
            row = conn.execute("SELECT COUNT(*) AS n FROM domain_events WHERE delivered = FALSE").fetchone()
            return int(row["n"])
        finally:
            if owned:
                conn.close()