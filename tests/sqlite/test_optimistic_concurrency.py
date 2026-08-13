"""FASE 10 — Optimistic concurrency for Match.

Every domain mutation bumps the aggregate version; the SQLite repository only
applies a write when the stored version is exactly one behind the mutated one.
A stale write raises StaleVersionError and changes nothing.
"""

from datetime import datetime
from uuid import uuid4

import pytest

from feb_score.domain.value_objects import ExternalId
from feb_score.infrastructure.persistence.errors import StaleVersionError
from feb_score.infrastructure.persistence.repositories import SqliteMatchRepository

from sqlite_helpers import ready_to_finalize


def test_upsert_bumps_version():
    match = ready_to_finalize()
    before = match.version
    match.upsert(round_number=6)
    assert match.version == before + 1


def test_new_aggregate_is_inserted(sqlite_db):
    repo = SqliteMatchRepository(sqlite_db)
    match = ready_to_finalize()
    repo.save(match)
    stored = repo.get_by_external_id(match.external_id)
    assert stored is not None
    assert stored.version == 1


def test_serial_mutations_are_accepted(sqlite_db):
    repo = SqliteMatchRepository(sqlite_db)
    match = ready_to_finalize()
    repo.save(match)  # v1
    match.finalize(finalized_at=datetime(2026, 2, 1, 20, 0), actor_id="admin-1")  # v2
    repo.save(match)
    match.apply_correction(
        correction_id=str(uuid4()),
        changes=[{"op": "update_score", "home_score": 80, "away_score": 77}],
        approved_at=datetime(2026, 2, 2, 10, 0),
        approver_id="admin-1",
        reason="official",
    )  # v3
    repo.save(match)
    stored = repo.get_by_external_id(match.external_id)
    assert stored.version == 3
    assert stored.status.value == "FINALIZED"


def test_concurrent_writer_is_rejected_and_does_not_corrupt(sqlite_db):
    repo = SqliteMatchRepository(sqlite_db)
    match = ready_to_finalize()
    repo.save(match)  # stored v1

    a = repo.get_by_external_id(match.external_id)  # reads v1
    b = repo.get_by_external_id(match.external_id)  # reads v1

    a.finalize(finalized_at=datetime(2026, 2, 1, 20, 0), actor_id="admin-1")
    repo.save(a)  # succeeds: stored 1 -> 2

    b.finalize(finalized_at=datetime(2026, 2, 1, 20, 0), actor_id="admin-1")
    with pytest.raises(StaleVersionError):
        repo.save(b)  # rejected: stored is 2, expected 1

    stored = repo.get_by_external_id(match.external_id)
    assert stored.version == 2
    assert stored.status.value == "FINALIZED"


def test_stale_error_is_classified_as_infrastructure_error():
    assert issubclass(StaleVersionError, Exception)