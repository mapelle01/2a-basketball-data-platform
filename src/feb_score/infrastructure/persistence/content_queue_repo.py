"""Persistent content queue repositories (SQLite + PostgreSQL).

Implements the ``ContentQueue`` surface the pipeline expects, backed by the
``content_queue`` table. Deduplicates by ``story.identity_key`` (UNIQUE
column): a story already queued is never inserted again — the pipeline can be
re-run over a round idempotently.

Storage: the full ContentItem (minus SVG) lives in the ``data`` JSON column;
the bulky rendered SVG in its own column so list queries stay light. Rows are
reconstructed via ``ContentItem.from_dict`` (SVG re-attached from its column).
"""

from __future__ import annotations

import json
from typing import List, Optional

from ...domain.content.queue import ContentItem, ContentStatus
from .postgres.repositories import _PgRepoMixin
from .repositories import _SqliteRepoMixin


def _row_columns(item: ContentItem) -> tuple:
    """The indexed query columns extracted from a ContentItem (order matters)."""
    return (
        item.content_id,
        item.story.identity_key,
        item.story.season_code,
        item.story.round_number,
        item.story.story_type.value,
        item.template_id,
        item.template_version,
        item.design_system_version,
        item.status.value,
        item.story.priority,
        item.created_at.isoformat(),
        item.updated_at.isoformat(),
        item.published_at.isoformat() if item.published_at else None,
        json.dumps(item.to_dict()),  # full item minus SVG (kept in its own column)
        item.rendered_svg,
    )


_COLUMNS = (
    "content_id, story_identity_key, season_code, round_number, story_type,"
    " template_id, template_version, design_system_version, status, priority,"
    " created_at, updated_at, published_at, data, rendered_svg"
)


def _reconstruct(data_json: str, rendered_svg: Optional[str]) -> ContentItem:
    data = json.loads(data_json)
    data["rendered_svg"] = rendered_svg
    return ContentItem.from_dict(data)


class SqliteContentQueueRepository(_SqliteRepoMixin):
    def __init__(self, db) -> None:
        self.db = db

    def add(self, item: ContentItem) -> bool:
        conn, owned = self._conn()
        try:
            existing = conn.execute(
                "SELECT 1 FROM content_queue WHERE story_identity_key = ?",
                (item.story.identity_key,),
            ).fetchone()
            if existing is not None:
                return False
            placeholders = ", ".join(["?"] * 15)
            conn.execute(
                f"INSERT INTO content_queue ({_COLUMNS}) VALUES ({placeholders})",
                _row_columns(item),
            )
            return True
        finally:
            if owned:
                conn.close()

    def update(self, item: ContentItem) -> None:
        """Persist a state transition on an existing row (keyed on content_id)."""
        conn, owned = self._conn()
        try:
            conn.execute(
                "UPDATE content_queue SET status = ?, updated_at = ?, published_at = ?,"
                " data = ?, rendered_svg = ? WHERE content_id = ?",
                (
                    item.status.value,
                    item.updated_at.isoformat(),
                    item.published_at.isoformat() if item.published_at else None,
                    json.dumps(item.to_dict()),
                    item.rendered_svg,
                    item.content_id,
                ),
            )
        finally:
            if owned:
                conn.close()

    def get(self, content_id: str) -> Optional[ContentItem]:
        conn, owned = self._conn()
        try:
            row = conn.execute(
                "SELECT data, rendered_svg FROM content_queue WHERE content_id = ?",
                (content_id,),
            ).fetchone()
            return _reconstruct(row["data"], row["rendered_svg"]) if row else None
        finally:
            if owned:
                conn.close()

    def by_story_identity(self, identity_key: str) -> Optional[ContentItem]:
        conn, owned = self._conn()
        try:
            row = conn.execute(
                "SELECT data, rendered_svg FROM content_queue WHERE story_identity_key = ?",
                (identity_key,),
            ).fetchone()
            return _reconstruct(row["data"], row["rendered_svg"]) if row else None
        finally:
            if owned:
                conn.close()

    def list_by_status(self, status: ContentStatus) -> List[ContentItem]:
        conn, owned = self._conn()
        try:
            rows = conn.execute(
                "SELECT data, rendered_svg FROM content_queue WHERE status = ?"
                " ORDER BY priority DESC, created_at",
                (status.value,),
            ).fetchall()
            return [_reconstruct(r["data"], r["rendered_svg"]) for r in rows]
        finally:
            if owned:
                conn.close()

    def all(self) -> List[ContentItem]:
        conn, owned = self._conn()
        try:
            rows = conn.execute(
                "SELECT data, rendered_svg FROM content_queue"
                " ORDER BY priority DESC, created_at"
            ).fetchall()
            return [_reconstruct(r["data"], r["rendered_svg"]) for r in rows]
        finally:
            if owned:
                conn.close()

    def purge(self, statuses=None) -> int:
        """Delete discarded items. Mirrors the in-memory queue's guard: only
        PURGEABLE_STATUSES are ever removed."""
        from ...domain.content.queue import PURGEABLE_STATUSES

        targets = tuple(statuses or PURGEABLE_STATUSES)
        forbidden = [s for s in targets if s not in PURGEABLE_STATUSES]
        if forbidden:
            raise ValueError(
                f"refusing to purge {', '.join(s.value for s in forbidden)}; "
                f"only {', '.join(s.value for s in PURGEABLE_STATUSES)} can be purged"
            )
        placeholders = ",".join("?" for _ in targets)
        conn, owned = self._conn()
        try:
            cur = conn.execute(
                f"DELETE FROM content_queue WHERE status IN ({placeholders})",
                tuple(s.value for s in targets),
            )
            return cur.rowcount or 0
        finally:
            if owned:
                conn.close()

    def seen_story_type_in_round(
        self, story_type: str, season_code: str, round_number: Optional[int]
    ) -> bool:
        """Novelty helper: has this story type already been queued for this
        round? (Enables real novelty scoring across pipeline runs.)"""
        conn, owned = self._conn()
        try:
            row = conn.execute(
                "SELECT 1 FROM content_queue WHERE story_type = ? AND season_code = ?"
                " AND round_number IS ? LIMIT 1",
                (story_type, season_code, round_number),
            ).fetchone()
            return row is not None
        finally:
            if owned:
                conn.close()


class PgContentQueueRepository(_PgRepoMixin):
    def __init__(self, db) -> None:
        self.db = db

    def add(self, item: ContentItem) -> bool:
        conn, owned = self._conn()
        try:
            existing = conn.execute(
                "SELECT 1 FROM content_queue WHERE story_identity_key = %s",
                (item.story.identity_key,),
            ).fetchone()
            if existing is not None:
                return False
            placeholders = ", ".join(["%s"] * 15)
            conn.execute(
                f"INSERT INTO content_queue ({_COLUMNS}) VALUES ({placeholders})",
                _row_columns(item),
            )
            return True
        finally:
            if owned:
                conn.close()

    def update(self, item: ContentItem) -> None:
        conn, owned = self._conn()
        try:
            conn.execute(
                "UPDATE content_queue SET status = %s, updated_at = %s, published_at = %s,"
                " data = %s, rendered_svg = %s WHERE content_id = %s",
                (
                    item.status.value,
                    item.updated_at.isoformat(),
                    item.published_at.isoformat() if item.published_at else None,
                    json.dumps(item.to_dict()),
                    item.rendered_svg,
                    item.content_id,
                ),
            )
        finally:
            if owned:
                conn.close()

    def get(self, content_id: str) -> Optional[ContentItem]:
        return self._one("content_id = %s", (content_id,))

    def by_story_identity(self, identity_key: str) -> Optional[ContentItem]:
        return self._one("story_identity_key = %s", (identity_key,))

    def _one(self, where: str, params: tuple) -> Optional[ContentItem]:
        conn, owned = self._conn()
        try:
            row = conn.execute(
                f"SELECT data::text AS data, rendered_svg FROM content_queue WHERE {where}",
                params,
            ).fetchone()
            return _reconstruct(row["data"], row["rendered_svg"]) if row else None
        finally:
            if owned:
                conn.close()

    def list_by_status(self, status: ContentStatus) -> List[ContentItem]:
        conn, owned = self._conn()
        try:
            rows = conn.execute(
                "SELECT data::text AS data, rendered_svg FROM content_queue WHERE status = %s"
                " ORDER BY priority DESC, created_at",
                (status.value,),
            ).fetchall()
            return [_reconstruct(r["data"], r["rendered_svg"]) for r in rows]
        finally:
            if owned:
                conn.close()

    def all(self) -> List[ContentItem]:
        conn, owned = self._conn()
        try:
            rows = conn.execute(
                "SELECT data::text AS data, rendered_svg FROM content_queue"
                " ORDER BY priority DESC, created_at"
            ).fetchall()
            return [_reconstruct(r["data"], r["rendered_svg"]) for r in rows]
        finally:
            if owned:
                conn.close()

    def purge(self, statuses=None) -> int:
        """Delete discarded items. Same guard as the in-memory queue: only
        PURGEABLE_STATUSES are ever removed."""
        from ...domain.content.queue import PURGEABLE_STATUSES

        targets = tuple(statuses or PURGEABLE_STATUSES)
        forbidden = [s for s in targets if s not in PURGEABLE_STATUSES]
        if forbidden:
            raise ValueError(
                f"refusing to purge {', '.join(s.value for s in forbidden)}; "
                f"only {', '.join(s.value for s in PURGEABLE_STATUSES)} can be purged"
            )
        conn, owned = self._conn()
        try:
            cur = conn.execute(
                "DELETE FROM content_queue WHERE status = ANY(%s)",
                ([s.value for s in targets],),
            )
            return cur.rowcount or 0
        finally:
            if owned:
                conn.close()
    def seen_story_type_in_round(
        self, story_type: str, season_code: str, round_number: Optional[int]
    ) -> bool:
        conn, owned = self._conn()
        try:
            row = conn.execute(
                "SELECT 1 FROM content_queue WHERE story_type = %s AND season_code = %s"
                " AND round_number IS NOT DISTINCT FROM %s LIMIT 1",
                (story_type, season_code, round_number),
            ).fetchone()
            return row is not None
        finally:
            if owned:
                conn.close()
