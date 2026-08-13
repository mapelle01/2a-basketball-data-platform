"""FASE 10 — SQLite concurrency across threads.

Single-writer reality: SQLite serializes writers (BEGIN IMMEDIATE + busy_timeout).
The invariants that MUST hold under parallelism are the optimistic-concurrency
ones: no silent lost update, and no corruption. WAL allows concurrent readers.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from uuid import uuid4

from feb_score.domain.value_objects import ExternalId, MatchId
from feb_score.infrastructure.persistence.errors import StaleVersionError
from feb_score.infrastructure.persistence.repositories import SqliteMatchRepository

from sqlite_helpers import finalized_match, ready_to_finalize


def test_writers_on_different_matches_all_succeed(sqlite_db):
    repo = SqliteMatchRepository(sqlite_db)

    def writer(i: int) -> str:
        match = finalized_match()
        match.external_id = ExternalId(f"m-{i}")
        match.match_id = MatchId(str(uuid4()))
        match.clear_events()
        repo.save(match)
        stored = repo.get_by_external_id(match.external_id)
        assert stored.external_id.value == f"m-{i}"
        return f"m-{i}"

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(writer, range(8)))

    assert sorted(results) == [f"m-{i}" for i in range(8)]
    assert len(list(repo.list_by_season("feb-comp", "2025-2026"))) == 8


def test_writers_on_same_match_never_lose_updates(sqlite_db):
    repo = SqliteMatchRepository(sqlite_db)
    match = ready_to_finalize()
    repo.save(match)  # v1

    barrier = threading.Barrier(5)
    outcomes = []

    def writer() -> str:
        snapshot = repo.get_by_external_id(match.external_id)
        barrier.wait()  # maximize overlap
        snapshot.finalize(finalized_at=datetime(2026, 2, 1, 20, 0), actor_id="admin-1")
        try:
            repo.save(snapshot)
            return "ok"
        except StaleVersionError:
            return "stale"

    with ThreadPoolExecutor(max_workers=5) as pool:
        outcomes = list(pool.map(lambda _: writer(), range(5)))

    assert set(outcomes) <= {"ok", "stale"}  # only the safety valve may fire
    assert "ok" in outcomes

    # Invariant: final version = initial version + number of successfully applied writes.
    ok_count = outcomes.count("ok")
    stored = repo.get_by_external_id(match.external_id)
    assert stored is not None
    assert stored.version == 1 + ok_count
    assert stored.status.value == "FINALIZED"


def test_reader_sees_committed_data_during_writes(sqlite_db):
    repo = SqliteMatchRepository(sqlite_db)
    for i in range(6):
        match = finalized_match()
        match.external_id = ExternalId(f"m-{i}")
        match.match_id = MatchId(str(uuid4()))
        match.clear_events()
        repo.save(match)

    # WAL: a connection opening its own transaction can read while another writes.
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda _: repo.get_by_external_id(ExternalId("m-0")), range(12)))

    assert repo.get_by_external_id(ExternalId("m-0")).status.value == "FINALIZED"