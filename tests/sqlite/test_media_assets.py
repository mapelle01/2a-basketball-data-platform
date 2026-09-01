"""Media asset store — the FEB SCORE! media database.

The point of this store is RIGHTS: it must never hand back a photo that is not
approved, whose licence forbids the use, or whose licence has expired. Those
rules are the tests below; the storage is almost incidental.
"""

from __future__ import annotations

import pytest

from feb_score.infrastructure.persistence.connection import SqliteDatabase
from feb_score.infrastructure.persistence.media_asset_repo import (
    SqliteMediaAssetRepository,
)

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


@pytest.fixture()
def repo(tmp_path):
    db = SqliteDatabase(str(tmp_path / "m.db"))
    db.migrate()
    return SqliteMediaAssetRepository(db)


def _add(repo, **kw):
    kw.setdefault("kind", "player")
    kw.setdefault("external_id", "p1")
    kw.setdefault("image", _PNG)
    kw.setdefault("content_type", "image/jpeg")
    return repo.add(**kw)


class TestStorage:
    def test_roundtrips_bytes_and_meta(self, repo):
        aid = _add(repo, photographer="Ana Foto", source="club",
                   tags={"orientation": "portrait", "face_visible": True})
        img = repo.get_image(aid)
        assert img.image == _PNG and img.content_type == "image/jpeg"
        meta = repo.list_meta("player", "p1")[0]
        assert meta.photographer == "Ana Foto"
        assert meta.tags == {"orientation": "portrait", "face_visible": True}
        assert meta.byte_size == len(_PNG)

    def test_many_photos_per_entity(self, repo):
        _add(repo, role="primary"); _add(repo, role="action"); _add(repo, role="action")
        assert len(repo.list_meta("player", "p1")) == 3

    def test_rejects_bad_kind_and_role(self, repo):
        with pytest.raises(ValueError):
            _add(repo, kind="coach")
        with pytest.raises(ValueError):
            _add(repo, role="selfie")

    def test_delete(self, repo):
        aid = _add(repo)
        assert repo.delete(aid) is True
        assert repo.get_image(aid) is None


class TestRightsSelection:
    """select() is the licence gate — the whole reason this store exists."""

    def test_never_returns_an_unapproved_photo(self, repo):
        _add(repo, approved=False)
        assert repo.select("player", "p1") is None

    def test_returns_an_approved_photo(self, repo):
        _add(repo, approved=True, photographer="OK")
        chosen = repo.select("player", "p1")
        assert chosen is not None and chosen.photographer == "OK"

    def test_commercial_use_is_enforced_when_required(self, repo):
        _add(repo, approved=True, commercial_use=False)
        # fine for editorial…
        assert repo.select("player", "p1") is not None
        # …but not when the caller needs commercial rights
        assert repo.select("player", "p1", require_commercial=True) is None

    def test_a_commercial_photo_satisfies_both(self, repo):
        _add(repo, approved=True, commercial_use=True)
        assert repo.select("player", "p1", require_commercial=True) is not None

    def test_expired_licence_is_never_used(self, repo):
        _add(repo, approved=True, expiry="2020-01-01")
        assert repo.select("player", "p1", today="2026-01-01") is None
        # still valid before it expires
        assert repo.select("player", "p1", today="2019-06-01") is not None

    def test_primary_is_preferred_over_action(self, repo):
        _add(repo, approved=True, role="action", photographer="ACTION")
        _add(repo, approved=True, role="primary", photographer="PRIMARY")
        assert repo.select("player", "p1").photographer == "PRIMARY"

    def test_promote_primary_swaps_the_current_primary(self, repo):
        """Only one primary per entity. Promoting must demote whoever held it
        so a UNIQUE-like invariant is enforced at write time — never let the
        library drift into two primaries."""
        a = _add(repo, role="primary", approved=True)
        b = _add(repo, role="alternate", approved=True)
        assert repo.promote_primary(b) is True
        by_id = {m.asset_id: m for m in repo.list_meta("player", "p1")}
        assert by_id[b].role == "primary"
        assert by_id[a].role == "alternate"

    def test_promote_missing_returns_false(self, repo):
        assert repo.promote_primary("nope") is False

    def test_get_meta_returns_none_when_absent(self, repo):
        assert repo.get_meta("nope") is None


class TestScoping:
    def test_selection_is_scoped_to_the_entity(self, repo):
        _add(repo, external_id="p1", approved=True)
        assert repo.select("player", "p2") is None
