"""FASE 7 — Persistence semantics integration tests.

Documents the current in-memory repository contract: repositories store object
references (no serialization/reconstruction round-trip) while still preserving
identity, status, and derived data across save/get.
"""

from datetime import datetime

from feb_score.application.repositories.in_memory import (
    InMemoryCompetitionRepository,
    InMemoryLeaderboardRepository,
    InMemoryMatchRepository,
    InMemoryPlayerRepository,
    InMemoryRatingRepository,
    InMemoryStandingRepository,
    InMemoryTeamRepository,
)
from feb_score.domain.competition.model import Competition
from feb_score.domain.value_objects import CompetitionId, ExternalId, LeaderboardId, SeasonCode, TeamId

from helpers import finalized_match, make_player, make_team


def test_match_repository_round_trip_preserves_identity_and_status():
    repo = InMemoryMatchRepository()
    match = finalized_match()
    repo.save(match)

    stored = repo.get_by_external_id(ExternalId("2513600"))
    assert stored.match_id == match.match_id
    assert stored.status.value == "FINALIZED"
    assert stored.score_summary.home_score == 80
    assert stored.external_id == match.external_id


def test_match_repository_stores_object_reference():
    """Reference-store semantics: mutations to the stored object are visible through the repo."""
    repo = InMemoryMatchRepository()
    match = finalized_match()
    repo.save(match)

    match.version = 99
    assert repo.get_by_external_id(ExternalId("2513600")).version == 99


def test_leaderboard_repository_round_trip():
    repo = InMemoryLeaderboardRepository()
    mrepo = InMemoryMatchRepository()
    mrepo.save(finalized_match())
    from feb_score.domain.leaderboard.model import Leaderboard

    board = Leaderboard.from_matches(
        season_code=SeasonCode("2025-2026"),
        category="points_per_game",
        matches=mrepo.list_by_season(CompetitionId("unknown"), SeasonCode("2025-2026")),
        min_games=0,
        top_n=10,
        generated_at=datetime.utcnow(),
    )
    repo.save(board)

    stored = repo.get_by_id(board.leaderboard_id)
    assert stored is board
    assert stored.leaderboard_id == board.leaderboard_id
    assert stored.category == "points_per_game"
    assert stored.entries  # entries survived


def test_leaderboard_repository_missing_id_returns_none():
    repo = InMemoryLeaderboardRepository()
    assert repo.get_by_id(LeaderboardId(str(__import__("uuid").uuid4()))) is None


def test_player_team_competition_round_trips():
    prepo = InMemoryPlayerRepository()
    trepo = InMemoryTeamRepository()
    crepo = InMemoryCompetitionRepository()

    player = make_player()
    team = make_team()
    competition = Competition(external_id=ExternalId("feb-comp-ext"), competition_id=CompetitionId("feb-comp"), name="League")
    prepo.save(player)
    trepo.save(team)
    crepo.save(competition)

    assert prepo.get_by_external_id(ExternalId("pl-987")).player_id == player.player_id
    assert trepo.get_by_external_id(ExternalId("team-123")).team_id == team.team_id
    assert crepo.get_by_external_id(ExternalId("feb-comp-ext")).name == "League"


def test_standing_and_rating_repositories_accumulate_without_id_collisions():
    srepo = InMemoryStandingRepository()
    rrepo = InMemoryRatingRepository()
    mrepo = InMemoryMatchRepository()
    mrepo.save(finalized_match())

    from feb_score.application.use_cases.handlers import (
        ComputePlayerRatingHandler,
        GenerateStandingSnapshotHandler,
    )
    from feb_score.application.commands.commands import (
        ComputePlayerRatingCommand,
        GenerateStandingSnapshotCommand,
    )
    from feb_score.domain.value_objects import Actor, CommandMeta

    base = {
        "command_id": str(__import__("uuid").uuid4()),
        "meta": CommandMeta(version="1.0", issued_at=datetime.utcnow()),
        "actor": Actor(id="a", role="system"),
    }
    GenerateStandingSnapshotHandler(srepo, mrepo).handle(
        GenerateStandingSnapshotCommand(**{
            **base,
            "payload": {
                "competition_id": "unknown", "season_code": "2025-2026",
                "as_of": "2026-02-01T23:59:59Z", "rules_version": "rules-v1",
            },
        })
    )
    ComputePlayerRatingHandler(mrepo, rrepo).handle(
        ComputePlayerRatingCommand(**{
            **base,
            "payload": {"player_external_id": "pl-1", "season_code": "2025-2026", "rating_version": "v1.0"},
        })
    )

    assert len(srepo._standings) == 1
    assert srepo._standings[0].season_code == SeasonCode("2025-2026")
    assert len(rrepo._ratings) == 1
    assert rrepo._ratings[0].player_external_id == ExternalId("pl-1")