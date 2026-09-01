"""Media asset store — the FEB SCORE! media database.

An evolution of ``image_overrides``: MANY photos per (kind, external_id), each
with rights metadata, so the system can hold a licensed library and pick the
right photo per post WITHOUT ever using an unlicensed one.

The licence gate is ``approved`` (and ``commercial_use``): ``select`` only ever
returns a photo that is approved — and, when commercial use is required, one
whose licence allows it — never expired. Bytes live in the row (the container
filesystem is wiped on every deploy). Two backends, one shape, sharing all the
column/selection logic through a mixin so the rights rules cannot drift apart.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from .connection import SqliteDatabase, active_connection
from .postgres.connection import PgDatabase, pg_active_connection

VALID_KINDS = ("player", "team")
VALID_ROLES = ("primary", "action", "alternate")

# Meta columns, in order — everything EXCEPT the image bytes.
_META_COLS = (
    "asset_id", "kind", "external_id", "role", "approved", "content_type",
    "byte_size", "source", "source_url", "photographer", "copyright",
    "license_type", "commercial_use", "date_acquired", "expiry", "tags",
    "notes", "created_at", "updated_at",
)


@dataclass(frozen=True)
class MediaAssetMeta:
    """Everything about a media asset except the bytes."""
    asset_id: str
    kind: str
    external_id: str
    role: str
    approved: bool
    content_type: str
    byte_size: int
    source: Optional[str]
    source_url: Optional[str]
    photographer: Optional[str]
    copyright: Optional[str]
    license_type: Optional[str]
    commercial_use: bool
    date_acquired: Optional[str]
    expiry: Optional[str]
    tags: Dict[str, Any]
    notes: Optional[str]
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class MediaImage:
    content_type: str
    image: bytes


def _check_kind(kind: str) -> None:
    if kind not in VALID_KINDS:
        raise ValueError(f"kind must be one of {VALID_KINDS}, got {kind!r}")


def _check_role(role: str) -> None:
    if role not in VALID_ROLES:
        raise ValueError(f"role must be one of {VALID_ROLES}, got {role!r}")


def _row_to_meta(r: Any) -> MediaAssetMeta:
    return MediaAssetMeta(
        asset_id=r["asset_id"], kind=r["kind"], external_id=r["external_id"],
        role=r["role"], approved=bool(r["approved"]), content_type=r["content_type"],
        byte_size=r["byte_size"], source=r["source"], source_url=r["source_url"],
        photographer=r["photographer"], copyright=r["copyright"],
        license_type=r["license_type"], commercial_use=bool(r["commercial_use"]),
        date_acquired=r["date_acquired"], expiry=r["expiry"],
        tags=json.loads(r["tags"]) if r["tags"] else {},
        notes=r["notes"], created_at=r["created_at"], updated_at=r["updated_at"],
    )


def _pick(metas: List[MediaAssetMeta], *, require_commercial: bool,
          today: Optional[str]) -> Optional[MediaAssetMeta]:
    """THE rights rule, in one place: choose the photo to actually use.

    Only approved photos are ever eligible; when commercial use is required, the
    licence must allow it; an expired licence is never used. Among the eligible,
    a 'primary' photo wins, then the most recently acquired.
    """
    today = today or date.today().isoformat()
    eligible = [
        m for m in metas
        if m.approved
        and (not require_commercial or m.commercial_use)
        and not (m.expiry and m.expiry < today)
    ]
    eligible.sort(
        key=lambda m: (m.role == "primary", m.date_acquired or "", m.created_at),
        reverse=True,
    )
    return eligible[0] if eligible else None


class _MediaRepoMixin:
    """Shared column/selection logic; subclasses supply the placeholder and the
    connection accessor so the two backends cannot drift on the rights rules."""

    _ph = "?"  # parameter placeholder ("?" sqlite, "%s" postgres)

    def _conn(self) -> Tuple[object, bool]:  # pragma: no cover - overridden
        raise NotImplementedError

    def add(
        self, kind: str, external_id: str, image: bytes, content_type: str, *,
        role: str = "primary", approved: bool = False,
        source: Optional[str] = None, source_url: Optional[str] = None,
        photographer: Optional[str] = None, copyright: Optional[str] = None,
        license_type: Optional[str] = None, commercial_use: bool = False,
        date_acquired: Optional[str] = None, expiry: Optional[str] = None,
        tags: Optional[Dict[str, Any]] = None, notes: Optional[str] = None,
    ) -> str:
        _check_kind(kind); _check_role(role)
        asset_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        ph = ", ".join([self._ph] * 20)
        conn, owned = self._conn()
        try:
            conn.execute(
                "INSERT INTO media_assets (asset_id, kind, external_id, role,"
                " approved, content_type, image, byte_size, source, source_url,"
                " photographer, copyright, license_type, commercial_use,"
                " date_acquired, expiry, tags, notes, created_at, updated_at)"
                f" VALUES ({ph})",
                (asset_id, kind, external_id, role, int(approved), content_type,
                 image, len(image), source, source_url, photographer, copyright,
                 license_type, int(commercial_use), date_acquired, expiry,
                 json.dumps(tags) if tags else None, notes, now, now),
            )
            return asset_id
        finally:
            if owned:
                conn.close()

    def _meta_select(self) -> str:
        return "SELECT " + ", ".join(_META_COLS) + " FROM media_assets"

    def list_meta(
        self, kind: Optional[str] = None, external_id: Optional[str] = None
    ) -> List[MediaAssetMeta]:
        clauses, params = [], []
        if kind is not None:
            _check_kind(kind); clauses.append(f"kind = {self._ph}"); params.append(kind)
        if external_id is not None:
            clauses.append(f"external_id = {self._ph}"); params.append(external_id)
        sql = self._meta_select()
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC"
        conn, owned = self._conn()
        try:
            rows = conn.execute(sql, tuple(params)).fetchall()
            return [_row_to_meta(r) for r in rows]
        finally:
            if owned:
                conn.close()

    def get_image(self, asset_id: str) -> Optional[MediaImage]:
        conn, owned = self._conn()
        try:
            row = conn.execute(
                f"SELECT content_type, image FROM media_assets WHERE asset_id = {self._ph}",
                (asset_id,),
            ).fetchone()
            if row is None:
                return None
            return MediaImage(content_type=row["content_type"], image=bytes(row["image"]))
        finally:
            if owned:
                conn.close()

    def select(
        self, kind: str, external_id: str, *,
        require_commercial: bool = False, today: Optional[str] = None,
    ) -> Optional[MediaAssetMeta]:
        """The photo to actually use for this entity, or None. Respects the
        licence: never returns an unapproved, wrong-licence or expired photo."""
        _check_kind(kind)
        return _pick(self.list_meta(kind, external_id),
                     require_commercial=require_commercial, today=today)

    def get_meta(self, asset_id: str) -> Optional[MediaAssetMeta]:
        conn, owned = self._conn()
        try:
            row = conn.execute(
                f"{self._meta_select()} WHERE asset_id = {self._ph}", (asset_id,),
            ).fetchone()
            return _row_to_meta(row) if row is not None else None
        finally:
            if owned:
                conn.close()

    def promote_primary(self, asset_id: str) -> bool:
        """Make this asset the primary photo for its (kind, external_id),
        demoting whichever asset held that role. Enforced at write time so the
        rule ("at most one primary per entity") holds without a UNIQUE index
        that would collide with a swap."""
        meta = self.get_meta(asset_id)
        if meta is None:
            return False
        now = datetime.utcnow().isoformat()
        conn, owned = self._conn()
        try:
            conn.execute(
                f"UPDATE media_assets SET role = {self._ph}, updated_at = {self._ph}"
                f" WHERE kind = {self._ph} AND external_id = {self._ph}"
                f" AND role = {self._ph} AND asset_id <> {self._ph}",
                ("alternate", now, meta.kind, meta.external_id, "primary", asset_id),
            )
            conn.execute(
                f"UPDATE media_assets SET role = {self._ph}, updated_at = {self._ph}"
                f" WHERE asset_id = {self._ph}",
                ("primary", now, asset_id),
            )
            return True
        finally:
            if owned:
                conn.close()

    def set_approved(self, asset_id: str, approved: bool) -> bool:
        conn, owned = self._conn()
        try:
            cur = conn.execute(
                f"UPDATE media_assets SET approved = {self._ph}, updated_at = {self._ph}"
                f" WHERE asset_id = {self._ph}",
                (int(approved), datetime.utcnow().isoformat(), asset_id),
            )
            return cur.rowcount > 0
        finally:
            if owned:
                conn.close()

    def delete(self, asset_id: str) -> bool:
        conn, owned = self._conn()
        try:
            cur = conn.execute(
                f"DELETE FROM media_assets WHERE asset_id = {self._ph}", (asset_id,)
            )
            return cur.rowcount > 0
        finally:
            if owned:
                conn.close()


class SqliteMediaAssetRepository(_MediaRepoMixin):
    _ph = "?"

    def __init__(self, db: SqliteDatabase) -> None:
        self.db = db

    def _conn(self) -> Tuple[object, bool]:
        active = active_connection()
        if active is not None:
            return active, False
        return self.db.connect(), True


class PgMediaAssetRepository(_MediaRepoMixin):
    _ph = "%s"

    def __init__(self, db: PgDatabase) -> None:
        self.db = db

    def _conn(self) -> Tuple[object, bool]:
        active = pg_active_connection()
        if active is not None:
            return active, False
        return self.db.connect(), True
