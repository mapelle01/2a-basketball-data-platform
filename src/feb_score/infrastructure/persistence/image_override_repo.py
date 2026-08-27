"""Image override store — operator-supplied player photos and team crests.

The render path resolves imagery from FEB by default; an override lets an
operator replace a missing or poor image with one of their own. The bytes live
in a row (not on disk) because the container filesystem is wiped on every
deploy — a file would not survive the next release.

Two backends, one shape. Rows are keyed by ``(kind, external_id)`` with
``kind`` in {"player", "team"}. ``list_meta`` returns everything BUT the bytes,
so the gallery can show what is overridden without shipping every image twice.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional, Tuple

from .connection import SqliteDatabase, active_connection
from .postgres.connection import PgDatabase, pg_active_connection

VALID_KINDS = ("player", "team")


@dataclass(frozen=True)
class ImageOverride:
    kind: str
    external_id: str
    content_type: str
    image: bytes
    byte_size: int
    updated_at: str


@dataclass(frozen=True)
class OverrideMeta:
    """Everything about an override except the bytes."""
    kind: str
    external_id: str
    content_type: str
    byte_size: int
    updated_at: str


def _check_kind(kind: str) -> None:
    if kind not in VALID_KINDS:
        raise ValueError(f"kind must be one of {VALID_KINDS}, got {kind!r}")


class SqliteImageOverrideRepository:
    def __init__(self, db: SqliteDatabase) -> None:
        self.db = db

    def _conn(self) -> Tuple[object, bool]:
        active = active_connection()
        if active is not None:
            return active, False
        return self.db.connect(), True

    def get(self, kind: str, external_id: str) -> Optional[ImageOverride]:
        _check_kind(kind)
        conn, owned = self._conn()
        try:
            row = conn.execute(
                "SELECT kind, external_id, content_type, image, byte_size, updated_at"
                " FROM image_overrides WHERE kind = ? AND external_id = ?",
                (kind, external_id),
            ).fetchone()
            if row is None:
                return None
            return ImageOverride(
                kind=row["kind"], external_id=row["external_id"],
                content_type=row["content_type"], image=bytes(row["image"]),
                byte_size=row["byte_size"], updated_at=row["updated_at"],
            )
        finally:
            if owned:
                conn.close()

    def put(self, kind: str, external_id: str, image: bytes, content_type: str) -> None:
        _check_kind(kind)
        conn, owned = self._conn()
        try:
            conn.execute(
                "INSERT INTO image_overrides"
                " (kind, external_id, content_type, image, byte_size, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (kind, external_id) DO UPDATE SET"
                " content_type = excluded.content_type, image = excluded.image,"
                " byte_size = excluded.byte_size, updated_at = excluded.updated_at",
                (kind, external_id, content_type, image, len(image),
                 datetime.utcnow().isoformat()),
            )
        finally:
            if owned:
                conn.close()

    def delete(self, kind: str, external_id: str) -> bool:
        _check_kind(kind)
        conn, owned = self._conn()
        try:
            cur = conn.execute(
                "DELETE FROM image_overrides WHERE kind = ? AND external_id = ?",
                (kind, external_id),
            )
            return cur.rowcount > 0
        finally:
            if owned:
                conn.close()

    def list_meta(self) -> Dict[Tuple[str, str], OverrideMeta]:
        conn, owned = self._conn()
        try:
            rows = conn.execute(
                "SELECT kind, external_id, content_type, byte_size, updated_at"
                " FROM image_overrides"
            ).fetchall()
            return {
                (r["kind"], r["external_id"]): OverrideMeta(
                    kind=r["kind"], external_id=r["external_id"],
                    content_type=r["content_type"], byte_size=r["byte_size"],
                    updated_at=r["updated_at"],
                )
                for r in rows
            }
        finally:
            if owned:
                conn.close()


class PgImageOverrideRepository:
    def __init__(self, db: PgDatabase) -> None:
        self.db = db

    def _conn(self) -> Tuple[object, bool]:
        active = pg_active_connection()
        if active is not None:
            return active, False
        return self.db.connect(), True

    def get(self, kind: str, external_id: str) -> Optional[ImageOverride]:
        _check_kind(kind)
        conn, owned = self._conn()
        try:
            row = conn.execute(
                "SELECT kind, external_id, content_type, image, byte_size, updated_at"
                " FROM image_overrides WHERE kind = %s AND external_id = %s",
                (kind, external_id),
            ).fetchone()
            if row is None:
                return None
            return ImageOverride(
                kind=row["kind"], external_id=row["external_id"],
                content_type=row["content_type"], image=bytes(row["image"]),
                byte_size=row["byte_size"], updated_at=row["updated_at"],
            )
        finally:
            if owned:
                conn.close()

    def put(self, kind: str, external_id: str, image: bytes, content_type: str) -> None:
        _check_kind(kind)
        conn, owned = self._conn()
        try:
            conn.execute(
                "INSERT INTO image_overrides"
                " (kind, external_id, content_type, image, byte_size, updated_at)"
                " VALUES (%s, %s, %s, %s, %s, %s)"
                " ON CONFLICT (kind, external_id) DO UPDATE SET"
                " content_type = EXCLUDED.content_type, image = EXCLUDED.image,"
                " byte_size = EXCLUDED.byte_size, updated_at = EXCLUDED.updated_at",
                (kind, external_id, content_type, image, len(image),
                 datetime.utcnow().isoformat()),
            )
        finally:
            if owned:
                conn.close()

    def delete(self, kind: str, external_id: str) -> bool:
        _check_kind(kind)
        conn, owned = self._conn()
        try:
            cur = conn.execute(
                "DELETE FROM image_overrides WHERE kind = %s AND external_id = %s",
                (kind, external_id),
            )
            return cur.rowcount > 0
        finally:
            if owned:
                conn.close()

    def list_meta(self) -> Dict[Tuple[str, str], OverrideMeta]:
        conn, owned = self._conn()
        try:
            rows = conn.execute(
                "SELECT kind, external_id, content_type, byte_size, updated_at"
                " FROM image_overrides"
            ).fetchall()
            return {
                (r["kind"], r["external_id"]): OverrideMeta(
                    kind=r["kind"], external_id=r["external_id"],
                    content_type=r["content_type"], byte_size=r["byte_size"],
                    updated_at=r["updated_at"],
                )
                for r in rows
            }
        finally:
            if owned:
                conn.close()
