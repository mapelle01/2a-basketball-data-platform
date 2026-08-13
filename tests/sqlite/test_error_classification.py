"""FASE 10 — Error classification: business errors vs infrastructure errors.

Business failures (DomainError) are domain logic and must surface unchanged.
Infrastructure failures (persistence, locking, corruption) use
``InfrastructureError`` so entrypoints can react without mixing the two families.
"""

import json

import pytest

from feb_score.domain.common import DomainError
from feb_score.domain.match.model import MatchAlreadyFinalized
from feb_score.infrastructure.persistence.errors import (
    CorruptedRecordError,
    InfrastructureError,
    StaleVersionError,
)

from sqlite_helpers import finalized_match


def test_infrastructure_errors_share_a_base():
    assert issubclass(StaleVersionError, InfrastructureError)
    assert issubclass(CorruptedRecordError, InfrastructureError)


def test_domain_errors_are_not_infrastructure_errors():
    assert not issubclass(MatchAlreadyFinalized, InfrastructureError)
    assert not issubclass(DomainError, InfrastructureError)


def test_domain_error_propagates_through_unit_of_work(sqlite_db):
    from feb_score.infrastructure.persistence.repositories import SqliteMatchRepository

    repo = SqliteMatchRepository(sqlite_db)
    match = finalized_match()  # already FINALIZED
    repo.save(match)

    with sqlite_db.unit_of_work():
        with pytest.raises(MatchAlreadyFinalized):
            match.finalize(finalized_at=__import__("datetime").datetime.utcnow())

    # rollback kept the DB intact
    assert repo.get_by_external_id(match.external_id).status.value == "FINALIZED"


def test_corrupt_json_blob_raises_corrupted_record(sqlite_db):
    from feb_score.domain.value_objects import ExternalId
    from feb_score.infrastructure.persistence.repositories import SqlitePlayerRepository

    # `players.data` has no json_valid CHECK, so a corrupt blob can exist at rest.
    conn = sqlite_db.connect()
    try:
        conn.execute(
            "INSERT INTO players (player_id, external_id, name, data)"
            " VALUES (?, ?, ?, ?)",
            ("p1", "corrupt-1", "Broken", "{not valid json"),
        )
    finally:
        conn.close()

    repo = SqlitePlayerRepository(sqlite_db)
    with pytest.raises(CorruptedRecordError):
        repo.get_by_external_id(ExternalId("corrupt-1"))


def test_matches_table_rejects_corrupt_blob_via_check(sqlite_db):
    conn = sqlite_db.connect()
    try:
        with pytest.raises(Exception):
            conn.execute(
                "INSERT INTO matches (match_id, external_id, competition_id, season_code, status, version, data)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("m1", "bad-1", "c", "2025-2026", "SCHEDULED", "1", "{not valid json"),
            )
    finally:
        conn.close()


def test_stale_write_raises_with_clear_message(sqlite_db):
    from feb_score.application.persistence.serialization import match_from_dict, match_to_dict
    from feb_score.infrastructure.persistence.repositories import SqliteMatchRepository

    repo = SqliteMatchRepository(sqlite_db)
    match = finalized_match()  # v2
    repo.save(match)  # stored v2

    snapshot = match_from_dict(match_to_dict(match))  # another v2 snapshot
    snapshot.upsert(round_number=7)  # v3 in memory
    repo.save(snapshot)  # applies (stored 2 -> 3)

    stale = match_from_dict(match_to_dict(match))  # a v2 snapshot that missed the update
    stale.upsert(round_number=8)  # v3 in memory
    with pytest.raises(StaleVersionError) as excinfo:
        repo.save(stale)  # stored is 3, expected 2 -> rejected
    assert "2513600" in str(excinfo.value)