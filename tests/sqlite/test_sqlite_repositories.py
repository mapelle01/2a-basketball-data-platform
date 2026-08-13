"""FASE 9 — SQLite repository round-trips across real connection boundaries.

Every repository must demonstrate: aggregate -> SQLite -> connection closed ->
NEW connection -> load -> equivalent aggregate. In-memory-only saves are NOT
accepted as evidence of persistence.
"""

from datetime import datetime
from uuid import uuid4

from feb_score.infrastructure.persistence.connection import SqliteDatabase
from feb_score.infrastructure.persistence.repositories import (
    SqliteCompetitionRepository,
    SqliteCorrectionRepository,
    SqliteIdempotencyRepository,
    SqliteLeaderboardRepository,
    SqliteMatchRepository,
    SqlitePlayerRepository,
    SqlitePublicationRepository,
    SqliteRatingRepository,
    SqliteStandingRepository,
    SqliteTeamRepository,
)
from feb_score.domain.competition.model import RoundDefinition
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

from sqlite_helpers import finalized_match, make_competition, make_player, make_team, proposal, scheduled_match


def reopen(path):
    return SqliteDatabase(path)


# --- Match -------------------------------------------------------------
def test_match_survives_connection_close_and_reopen(sqlite_db, db_path):
    repo = SqliteMatchRepository(sqlite_db)
    match = finalized_match()
    repo.save(match)

    fresh = reopen(db_path)
    loaded = SqliteMatchRepository(fresh).get_by_external_id(ExternalId("2513600"))

    assert loaded is not None
    assert loaded.match_id == match.match_id
    assert loaded.status == MatchStatus("FINALIZED")
    assert loaded.score_summary.home_score == 80
    assert loaded.player_stats[0].points == 22
    assert loaded.version == 2
    assert loaded.correction_history == match.correction_history


def test_match_list_by_season_after_reopen(sqlite_db, db_path):
    repo = SqliteMatchRepository(sqlite_db)
    other = scheduled_match()
    other.external_id = ExternalId("2513601")
    other.match_id = MatchId(str(uuid4()))
    repo.save(finalized_match())
    repo.save(other)

    fresh = reopen(db_path)
    matches = list(SqliteMatchRepository(fresh).list_by_season(CompetitionId("feb-comp"), SeasonCode("2025-2026")))
    assert {str(m.external_id) for m in matches} == {"2513600", "2513601"}
    assert all(isinstance(m, type(finalized_match())) for m in matches)


# --- Player / Team -----------------------------------------------------
def test_player_survives_connection_close_and_reopen(sqlite_db, db_path):
    player = make_player()
    player.register_for_team(team_external_id="team-123", season_code=SeasonCode("2025-2026"), dorsal=12)
    SqlitePlayerRepository(sqlite_db).save(player)

    fresh = reopen(db_path)
    loaded = SqlitePlayerRepository(fresh).get_by_external_id(ExternalId("pl-987"))
    assert loaded is not None
    assert loaded.player_id == player.player_id
    assert loaded.registrations[0].dorsal == 12
    assert loaded.is_registered_for("team-123", SeasonCode("2025-2026"))


def test_team_survives_connection_close_and_reopen(sqlite_db, db_path):
    team = make_team()
    team.add_player_registration(player_external_id="pl-987", season_code=SeasonCode("2025-2026"), dorsal=12)
    SqliteTeamRepository(sqlite_db).save(team)

    fresh = reopen(db_path)
    loaded = SqliteTeamRepository(fresh).get_by_external_id(ExternalId("team-123"))
    assert loaded is not None
    assert loaded.registrations[0].player_external_id == "pl-987"
    assert loaded.has_player("pl-987", SeasonCode("2025-2026"))


# --- Competition -------------------------------------------------------
def test_competition_survives_connection_close_and_reopen(sqlite_db, db_path):
    competition = make_competition()
    season = competition.define_season(SeasonCode("2025-2026"), "rules-v1")
    season.add_round(RoundDefinition(number=1, label="Jornada 1"))
    SqliteCompetitionRepository(sqlite_db).save(competition)

    fresh = reopen(db_path)
    loaded = SqliteCompetitionRepository(fresh).get_by_external_id(ExternalId("feb-comp"))
    assert loaded is not None
    assert loaded.get_season(SeasonCode("2025-2026")).rounds[0].number == 1
    assert loaded.get_season(SeasonCode("2025-2026")).rules_version == "rules-v1"


# --- CorrectionProposal ------------------------------------------------
def test_correction_proposal_survives_connection_close_and_reopen(sqlite_db, db_path):
    p = proposal()
    SqliteCorrectionRepository(sqlite_db).save(p)

    fresh = reopen(db_path)
    loaded = SqliteCorrectionRepository(fresh).get_by_id(p.proposal_id.value)
    assert loaded is not None
    assert loaded.status == "PROPOSED"
    assert loaded.proposed_by.id == "editor-1"
    assert loaded.changes[0]["op"] == "update_score"


# --- Leaderboard -------------------------------------------------------
def test_leaderboard_survives_connection_close_and_reopen(sqlite_db, db_path):
    board = Leaderboard(
        leaderboard_id=LeaderboardId(str(uuid4())),
        season_code=SeasonCode("2025-2026"),
        category="points_per_game",
        generated_at=datetime(2026, 2, 1, 23, 59, 59),
        min_games=1,
        entries=[LeaderboardEntry(player_external_id="pl-1", team_external_id="team-home", games=10, value=22.5)],
    )
    SqliteLeaderboardRepository(sqlite_db).save(board)

    fresh = reopen(db_path)
    loaded = SqliteLeaderboardRepository(fresh).get_by_id(board.leaderboard_id)
    assert loaded is not None
    assert loaded.entries[0].value == 22.5
    assert loaded.category == "points_per_game"


# --- Rating / Standing / Publication (append-only, no get_by_id) -------
def test_rating_survives_connection_close_and_reopen(sqlite_db, db_path):
    rating = PlayerRating(
        player_external_id=ExternalId("pl-1"),
        season_code=SeasonCode("2025-2026"),
        rating_value=RatingValue(21.8),
        rating_version=RatingVersion("v1.0"),
        calculated_at=datetime(2026, 2, 1, 23, 59, 59),
        source_stats=[{"points": 22, "rebounds": 9, "assists": 5}],
    )
    SqliteRatingRepository(sqlite_db).save(rating)

    fresh = reopen(db_path)
    loaded = SqliteRatingRepository(fresh).list_all()
    assert len(loaded) == 1
    assert loaded[0].rating_value == RatingValue(21.8)
    assert loaded[0].source_stats[0]["points"] == 22


def test_standing_snapshot_survives_connection_close_and_reopen(sqlite_db, db_path):
    snapshot = StandingSnapshot(
        snapshot_id=SnapshotId(str(uuid4())),
        competition_id=CompetitionId("feb-comp"),
        season_code=SeasonCode("2025-2026"),
        generated_at=datetime(2026, 2, 1, 23, 59, 59),
        rounds_included=2,
        matches_count=1,
        rules_version="rules-v1",
        description="Round 2",
        entries=[StandingEntry(team_external_id="team-home", played=1, wins=1, losses=0, points_for=80, points_against=77, points_difference=3, points=2)],
    )
    SqliteStandingRepository(sqlite_db).save(snapshot)

    fresh = reopen(db_path)
    loaded = SqliteStandingRepository(fresh).list_all()
    assert len(loaded) == 1
    assert loaded[0].entries[0].points_difference == 3


def test_publication_survives_connection_close_and_reopen(sqlite_db, db_path):
    publication = Publication(
        publication_id=PublicationId(str(uuid4())),
        title="Report",
        content="Automated",
        template_id="tpl-1",
        references=[{"type": "match", "id": "2513600"}],
        created_at=datetime(2026, 2, 2, 8, 0),
        created_by=Actor(id="editor-1", role="editor"),
    )
    SqlitePublicationRepository(sqlite_db).save(publication)

    fresh = reopen(db_path)
    loaded = SqlitePublicationRepository(fresh).list_all()
    assert len(loaded) == 1
    assert loaded[0].references == [{"type": "match", "id": "2513600"}]
    assert loaded[0].created_by.role == "editor"


# --- Idempotency -------------------------------------------------------
def test_idempotency_survives_connection_close_and_reopen(sqlite_db, db_path):
    repo = SqliteIdempotencyRepository(sqlite_db)
    repo.mark_processed("cmd-1")

    fresh = reopen(db_path)
    assert SqliteIdempotencyRepository(fresh).has_processed("cmd-1")
    assert not SqliteIdempotencyRepository(fresh).has_processed("cmd-2")


# --- Missing keys ------------------------------------------------------
def test_get_missing_returns_none_after_reopen(sqlite_db, db_path):
    fresh = reopen(db_path)
    assert SqliteMatchRepository(fresh).get_by_external_id(ExternalId("nope")) is None
    assert SqlitePlayerRepository(fresh).get_by_external_id(ExternalId("nope")) is None
    assert SqliteTeamRepository(fresh).get_by_external_id(ExternalId("nope")) is None
    assert SqliteCompetitionRepository(fresh).get_by_external_id(ExternalId("nope")) is None
    assert SqliteCorrectionRepository(fresh).get_by_id("nope") is None
    assert SqliteLeaderboardRepository(fresh).get_by_id(LeaderboardId(str(uuid4()))) is None