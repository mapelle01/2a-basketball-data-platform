"""FASE 12 — Repository contract tests.

The SAME test bodies run against BOTH backends (parametrized ``backend``
fixture): SQLite and PostgreSQL. Passing here means the two implementations
respect the same interfaces and public semantics for repositories, transactions,
concurrency, idempotency, restart persistence, the outbox and the dispatcher.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from uuid import uuid4

import pytest

from feb_score.domain.leaderboard.model import Leaderboard, LeaderboardEntry
from feb_score.domain.publication.model import Publication
from feb_score.domain.ratings.model import PlayerRating
from feb_score.domain.standings.model import StandingEntry, StandingSnapshot
from feb_score.domain.value_objects import (
    Actor,
    CompetitionId,
    ExternalId,
    LeaderboardId,
    MatchId,
    MatchStatus,
    PublicationId,
    RatingValue,
    RatingVersion,
    SeasonCode,
    SnapshotId,
)
from feb_score.infrastructure.persistence.event_dispatcher import (
    IdempotentConsumer,
    RecordingPublisher,
)
from feb_score.infrastructure.persistence.errors import StaleVersionError

from sqlite_helpers import (
    create_match_command,
    finalize_command,
    finalized_match,
    make_competition,
    make_player,
    make_team,
    proposal,
    ready_to_finalize,
    scheduled_match,
)

CREATE_PAYLOAD = {
    "external_id": "2513600",
    "competition_id": "feb-comp",
    "season_code": "2025-2026",
    "round_number": 5,
    "scheduled_at": "2026-02-01T18:30:00Z",
    "home_team": {"external_id": "team-home", "name": "Home"},
    "away_team": {"external_id": "team-away", "name": "Away"},
    "source": {"id": "feb-api", "fetched_at": "2026-02-01T18:00:00Z", "s3_path": "s3://x"},
}


# ---------------------------------------------------------- repository round-trip
def test_match_round_trip_across_reopen(backend):
    db = backend.make_db()
    backend.repo(db, "match").save(finalized_match())

    fresh = backend.reopen(db)
    loaded = backend.repo(fresh, "match").get_by_external_id(ExternalId("2513600"))
    assert loaded is not None
    assert loaded.status == MatchStatus("FINALIZED")
    assert loaded.score_summary.home_score == 80
    assert loaded.player_stats[0].points == 22
    assert loaded.version == 2


def test_match_list_by_season_across_reopen(backend):
    db = backend.make_db()
    repo = backend.repo(db, "match")
    other = scheduled_match()
    other.external_id = ExternalId("2513601")
    other.match_id = MatchId(str(uuid4()))
    repo.save(finalized_match())
    repo.save(other)

    fresh = backend.reopen(db)
    matches = list(backend.repo(fresh, "match").list_by_season(CompetitionId("feb-comp"), SeasonCode("2025-2026")))
    assert {str(m.external_id) for m in matches} == {"2513600", "2513601"}


def test_player_round_trip_across_reopen(backend):
    db = backend.make_db()
    backend.repo(db, "player").save(make_player())
    loaded = backend.repo(backend.reopen(db), "player").get_by_external_id(ExternalId("pl-987"))
    assert loaded is not None and loaded.name == "Juan"


def test_team_round_trip_across_reopen(backend):
    db = backend.make_db()
    backend.repo(db, "team").save(make_team())
    loaded = backend.repo(backend.reopen(db), "team").get_by_external_id(ExternalId("team-123"))
    assert loaded is not None and loaded.name == "Club"


def test_competition_round_trip_across_reopen(backend):
    db = backend.make_db()
    competition = make_competition()
    competition.define_season(SeasonCode("2025-2026"), rules_version="rules-v1")
    backend.repo(db, "competition").save(competition)
    loaded = backend.repo(backend.reopen(db), "competition").get_by_external_id(ExternalId("feb-comp"))
    assert loaded is not None
    assert loaded.get_season(SeasonCode("2025-2026")) is not None


def test_correction_proposal_round_trip_across_reopen(backend):
    db = backend.make_db()
    backend.repo(db, "match").save(finalized_match())
    p = proposal()
    backend.repo(db, "correction").save(p)
    loaded = backend.repo(backend.reopen(db), "correction").get_by_id(str(p.proposal_id))
    assert loaded is not None and loaded.match_external_id == p.match_external_id


def test_standing_round_trip_across_reopen(backend):
    db = backend.make_db()
    snapshot = StandingSnapshot(
        snapshot_id=SnapshotId(str(uuid4())),
        competition_id=CompetitionId("feb-comp"),
        season_code=SeasonCode("2025-2026"),
        generated_at=datetime(2026, 2, 3, 12, 0),
        rounds_included=5,
        matches_count=1,
        rules_version="v1",
        entries=(
            StandingEntry(
                team_external_id="team-home", played=1, wins=1, losses=0,
                points_for=80, points_against=77, points_difference=3, points=2,
            ),
        ),
    )
    backend.repo(db, "standing").save(snapshot)
    fresh = backend.reopen(db)
    loaded = backend.repo(fresh, "standing").list_all()
    assert len(loaded) == 1 and loaded[0].entries[0].team_external_id == "team-home"


def test_leaderboard_round_trip_across_reopen(backend):
    db = backend.make_db()
    board = Leaderboard(
        leaderboard_id=LeaderboardId(str(uuid4())),
        season_code=SeasonCode("2025-2026"),
        category="points_per_game",
        generated_at=datetime(2026, 2, 3, 12, 0),
        min_games=1,
        entries=(LeaderboardEntry(player_external_id="pl-1", team_external_id="team-home", games=1, value=22.0),),
    )
    backend.repo(db, "leaderboard").save(board)
    loaded = backend.repo(backend.reopen(db), "leaderboard").get_by_id(board.leaderboard_id)
    assert loaded is not None and loaded.entries[0].value == 22.0


def test_rating_round_trip_across_reopen(backend):
    db = backend.make_db()
    rating = PlayerRating(
        player_external_id=ExternalId("pl-1"),
        season_code=SeasonCode("2025-2026"),
        rating_value=RatingValue(75.5),
        rating_version=RatingVersion("v1.0"),
        calculated_at=datetime(2026, 2, 3, 12, 0),
    )
    backend.repo(db, "rating").save(rating)
    loaded = backend.repo(backend.reopen(db), "rating").list_all()
    assert len(loaded) == 1 and loaded[0].rating_value == RatingValue(75.5)


def test_publication_round_trip_across_reopen(backend):
    db = backend.make_db()
    pub = Publication(
        publication_id=PublicationId(str(uuid4())),
        title="Match report",
        content="body",
        template_id="match-report",
        status="DRAFT",
        created_at=datetime(2026, 2, 3, 12, 0),
    )
    backend.repo(db, "publication").save(pub)
    loaded = backend.repo(backend.reopen(db), "publication").list_all()
    assert len(loaded) == 1 and loaded[0].template_id == "match-report"


def test_idempotency_mark_and_has(backend):
    db = backend.make_db()
    repo = backend.repo(db, "idempotency")
    assert repo.has_processed("c-1") is False
    repo.mark_processed("c-1")
    assert backend.repo(backend.reopen(db), "idempotency").has_processed("c-1") is True


def test_upsert_preserves_serialized_aggregate(backend):
    db = backend.make_db()
    from feb_score.application.persistence import serialization as S

    match = scheduled_match()
    backend.repo(db, "match").save(match)
    # mutate the in-memory aggregate (version bumps) and save again: upsert, one row
    match.upsert(round_number=6)
    backend.repo(db, "match").save(match)
    loaded = backend.repo(backend.reopen(db), "match").get_by_external_id(ExternalId("2513600"))
    assert loaded.round_number == 6
    assert loaded.version == 2


# ---------------------------------------------------- transactions + rollback
def test_unit_of_work_commits_state_events_and_idempotency(backend):
    db = backend.make_db()
    from feb_score.application.persistence import serialization as S

    with db.unit_of_work() as uow:
        backend.repo(db, "match").save(scheduled_match())
        backend.repo(db, "idempotency").mark_processed("c-x")
        from feb_score.domain.events import MatchUpserted
        from feb_score.domain.value_objects import EventMeta

        uow.append_events([
            MatchUpserted(event_id=str(uuid4()), meta=EventMeta(version="1.0", produced_at=datetime.utcnow()),
                          source={"origin": "system"}, payload={"external_id": "2513600"}),
        ])

    fresh = backend.reopen(db)
    assert backend.repo(fresh, "match").get_by_external_id(ExternalId("2513600")) is not None
    assert backend.repo(fresh, "idempotency").has_processed("c-x")
    assert backend.event_store(fresh).pending_count() == 1


def test_unit_of_work_rolls_back_everything_on_error(backend):
    db = backend.make_db()
    with pytest.raises(RuntimeError):
        with db.unit_of_work() as uow:
            backend.repo(db, "match").save(scheduled_match())
            backend.repo(db, "idempotency").mark_processed("c-x")
            raise RuntimeError("boom")

    fresh = backend.reopen(db)
    assert backend.repo(fresh, "match").get_by_external_id(ExternalId("2513600")) is None
    assert backend.repo(fresh, "idempotency").has_processed("c-x") is False
    assert backend.event_store(fresh).pending_count() == 0


def test_append_events_in_middle_failure_rolls_back_aggregate(backend):
    """A failure while persisting events must roll back the aggregate write too."""
    db = backend.make_db()
    with pytest.raises(AttributeError):
        with db.unit_of_work() as uow:
            backend.repo(db, "match").save(scheduled_match())
            uow.append_events([object()])  # invalid event -> append fails
    assert backend.repo(backend.reopen(db), "match").get_by_external_id(ExternalId("2513600")) is None


# ------------------------------------------------------------- optimistic lock
def test_stale_version_is_rejected(backend):
    db = backend.make_db()
    repo = backend.repo(db, "match")
    match = finalized_match()
    repo.save(match)

    fresh = backend.reopen(db)
    second = backend.repo(fresh, "match").get_by_external_id(ExternalId("2513600"))
    second.upsert(round_number=6)  # version 3
    backend.repo(fresh, "match").save(second)

    # the ORIGINAL snapshot is now stale (v2); saving it must be rejected
    with pytest.raises(StaleVersionError):
        repo.save(match)


def test_parallel_finalize_no_lost_update(backend):
    db = backend.make_db()
    backend.repo(db, "match").save(ready_to_finalize())
    gateway = backend.gateway(db)

    def finalize(_):
        try:
            return gateway.run(
                "finalize_match",
                command_id=str(uuid4()),
                actor={"id": "system", "role": "system"},
                payload={"match_external_id": "2513600"},
            )
        except StaleVersionError:
            return "stale"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(finalize, range(2)))

    match = backend.repo(db, "match").get_by_external_id(ExternalId("2513600"))
    assert match.status == MatchStatus("FINALIZED")
    # one real finalize applied (version 2); the other saw fresh state (stale or
    # validation-failed event). No lost update: at least one 2xx, never 0 real writes.
    assert any(o != "stale" for o in outcomes)
    assert match.version == 2
    assert match.score_summary.home_score == 80


# ------------------------------------------------------------------ idempotency
def test_replayed_command_id_produces_no_duplicate_state_or_events(backend):
    db = backend.make_db()
    gateway = backend.gateway(db)
    command_id = str(uuid4())

    first = gateway.run("create_or_update_match", command_id=command_id,
                        actor={"id": "system", "role": "system"}, payload=CREATE_PAYLOAD)
    assert len(first.events) == 1
    replay = gateway.run("create_or_update_match", command_id=command_id,
                         actor={"id": "system", "role": "system"}, payload=CREATE_PAYLOAD)
    assert replay.events == []

    matches = list(backend.repo(db, "match").list_by_season(CompetitionId("feb-comp"), SeasonCode("2025-2026")))
    assert len(matches) == 1
    assert matches[0].version == 1
    assert backend.event_store(db).pending_count() == 1


def test_idempotency_survives_restart(backend):
    db = backend.make_db()
    command_id = str(uuid4())
    assert backend.gateway(db).run(
        "create_or_update_match", command_id=command_id,
        actor={"id": "system", "role": "system"}, payload=CREATE_PAYLOAD,
    ).events

    fresh = backend.reopen(db)
    replay = backend.gateway(fresh).run(
        "create_or_update_match", command_id=command_id,
        actor={"id": "system", "role": "system"}, payload=CREATE_PAYLOAD,
    )
    assert replay.events == []
    assert len(list(backend.repo(fresh, "match").list_by_season(CompetitionId("feb-comp"), SeasonCode("2025-2026")))) == 1
    assert backend.event_store(fresh).pending_count() == 1


# ------------------------------------------------------------ restart persistence
def test_create_persists_across_restart(backend):
    db = backend.make_db()
    assert backend.gateway(db).run(
        "create_or_update_match", command_id=str(uuid4()),
        actor={"id": "system", "role": "system"}, payload=CREATE_PAYLOAD,
    ).events

    fresh = backend.reopen(db)
    match = backend.repo(fresh, "match").get_by_external_id(ExternalId("2513600"))
    assert match is not None and match.status == MatchStatus("SCHEDULED")
    assert backend.event_store(fresh).pending_count() == 1  # events survive restart


def test_finalize_flow_across_restart(backend):
    db = backend.make_db()
    backend.repo(db, "match").save(ready_to_finalize())
    assert backend.gateway(db).run(
        "finalize_match", command_id=str(uuid4()),
        actor={"id": "system", "role": "system"}, payload={"match_external_id": "2513600"},
    ).events

    fresh = backend.reopen(db)
    match = backend.repo(fresh, "match").get_by_external_id(ExternalId("2513600"))
    assert match.status == MatchStatus("FINALIZED")
    assert match.version == 2


# ------------------------------------------------------------ event store/outbox
def test_event_store_reconstructs_events(backend):
    db = backend.make_db()
    store = backend.event_store(db)
    assert store.pending_count() == 0
    gateway = backend.gateway(db)
    result = gateway.run("create_or_update_match", command_id=str(uuid4()),
                         actor={"id": "system", "role": "system"}, payload=CREATE_PAYLOAD)
    event_id = result.events[0].event_id
    assert store.pending_count() == 1

    rows = store.fetch_undelivered(10)
    assert len(rows) == 1 and rows[0]["event_id"] == event_id
    from feb_score.infrastructure.persistence.event_catalog import reconstruct_event

    event = reconstruct_event(rows[0])
    assert event.event_id == event_id
    assert event.payload["external_id"] == "2513600"


def test_dispatch_marks_delivered_only_after_publish(backend):
    db = backend.make_db()
    assert backend.gateway(db).run(
        "create_or_update_match", command_id=str(uuid4()),
        actor={"id": "system", "role": "system"}, payload=CREATE_PAYLOAD,
    ).events

    store = backend.event_store(db)
    assert store.pending_count() == 1

    failing = RecordingPublisher(fail_on=0)  # fails on the FIRST event
    assert backend.dispatcher(db, failing).dispatch() == 0
    assert store.pending_count() == 1  # not marked delivered

    healthy = RecordingPublisher()
    assert backend.dispatcher(db, healthy).dispatch() == 1
    assert store.pending_count() == 0  # delivered only after successful publish
    assert len(healthy.published) == 1


def test_dispatch_retry_after_failure_delivers_once(backend):
    db = backend.make_db()
    assert backend.gateway(db).run(
        "create_or_update_match", command_id=str(uuid4()),
        actor={"id": "system", "role": "system"}, payload=CREATE_PAYLOAD,
    ).events

    store = backend.event_store(db)
    consumer = RecordingPublisher()
    # fail the first delivery attempt, succeed on retry (restart-safe: new dispatcher)
    assert backend.dispatcher(db, RecordingPublisher(fail_on=0)).dispatch() == 0
    fresh = backend.reopen(db)
    assert backend.dispatcher(fresh, consumer).dispatch() == 1
    assert len(consumer.published) == 1
    assert backend.event_store(fresh).pending_count() == 0


def test_idempotent_consumer_deduplicates_redelivery(backend):
    db = backend.make_db()
    assert backend.gateway(db).run(
        "create_or_update_match", command_id=str(uuid4()),
        actor={"id": "system", "role": "system"}, payload=CREATE_PAYLOAD,
    ).events

    downstream = RecordingPublisher()
    consumer = IdempotentConsumer(downstream)
    # redeliver manually: at-least-once means the same event may arrive twice
    rows = backend.event_store(db).fetch_undelivered(10)
    from feb_score.infrastructure.persistence.event_catalog import reconstruct_event

    for row in rows:
        consumer.publish(reconstruct_event(row))
        consumer.publish(reconstruct_event(row))  # duplicate delivery
    assert len(downstream.published) == 1  # exactly once downstream


# ------------------------------------------------------------ application flows
def test_application_flow_finalize(backend):
    db = backend.make_db()
    gateway = backend.gateway(db)
    # seed a scoreful snapshot (version 1), then run the finalize use-case
    backend.repo(db, "match").save(ready_to_finalize())
    finalized = gateway.run("finalize_match", command_id=str(uuid4()),
                            actor={"id": "system", "role": "system"},
                            payload={"match_external_id": "2513600"})
    assert any(e.event_type == "match_validated" for e in finalized.events)

    match = backend.repo(db, "match").get_by_external_id(ExternalId("2513600"))
    assert match.status == MatchStatus("FINALIZED")
    assert match.version == 2


def test_gateway_read_side_consistent(backend):
    db = backend.make_db()
    gateway = backend.gateway(db)
    gateway.run("create_or_update_match", command_id=str(uuid4()),
                actor={"id": "system", "role": "system"}, payload=CREATE_PAYLOAD)
    dto = gateway.get_match("2513600")
    assert dto["status"] == "SCHEDULED"
    assert dto["home_team_id"] == "team-home"
    assert gateway.get_match("nope") is None