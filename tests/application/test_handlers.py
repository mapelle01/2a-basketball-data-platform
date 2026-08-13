from datetime import datetime
from uuid import uuid4

import pytest
from feb_score.application.commands.commands import (
    ApproveCorrectionCommand,
    CreateOrUpdateMatchCommand,
    ComputePlayerRatingCommand,
    GenerateLeaderboardCommand,
    GenerateStandingSnapshotCommand,
    ProposeCorrectionCommand,
    RegisterPlayerToSquadCommand,
)
from feb_score.application.repositories.in_memory import (
    InMemoryCompetitionRepository,
    InMemoryCorrectionRepository,
    InMemoryMatchRepository,
    InMemoryPlayerRepository,
    InMemoryPublicationRepository,
    InMemoryRatingRepository,
    InMemoryStandingRepository,
    InMemoryTeamRepository,
)
from feb_score.application.use_cases.handlers import (
    ApproveCorrectionHandler,
    CreateOrUpdateMatchHandler,
    ComputePlayerRatingHandler,
    GenerateStandingSnapshotHandler,
    ProposeCorrectionHandler,
    RegisterPlayerToSquadHandler,
)
from feb_score.domain.match.model import Match
from feb_score.domain.player.model import Player
from feb_score.domain.publication.model import Publication
from feb_score.domain.team.model import Team
from feb_score.domain.statistics.model import TeamStats, PlayerStats
from feb_score.domain.value_objects import PeriodScore, ScoreSummary
from feb_score.domain.value_objects import Actor, CommandMeta, CompetitionId, ExternalId, MatchId, PlayerId, PublicationId, SeasonCode, TeamId


def test_create_or_update_match_handler():
    match_repo = InMemoryMatchRepository()
    handler = CreateOrUpdateMatchHandler(match_repo)
    command = CreateOrUpdateMatchCommand(
        command_id=str(uuid4()),
        meta=CommandMeta(version="1.0", issued_at=datetime.utcnow()),
        actor=Actor(id="system-1", role="system"),
        payload={
            "external_id": "2513600",
            "competition_id": "feb-competition",
            "season_code": "2025-2026",
            "round_number": 5,
            "scheduled_at": "2026-02-01T18:30:00",
            "home_team": {"external_id": "team-home", "name": "Home Club"},
            "away_team": {"external_id": "team-away", "name": "Away Club"},
            "source": {"id": "feb-api", "fetched_at": "2026-02-01T18:00:00Z", "s3_path": "s3://x"},
        },
    )

    events = handler.handle(command)
    assert len(events) == 1
    saved = match_repo.get_by_external_id(ExternalId("2513600"))
    assert saved is not None
    assert saved.round_number == 5


def test_finalize_match_handler_valid():
    match_repo = InMemoryMatchRepository()
    match = Match(
        external_id=ExternalId("2513600"),
        match_id=MatchId(str(uuid4())),
        competition_id=CompetitionId("feb-competition"),
        season_code=SeasonCode("2025-2026"),
        round_number=5,
        home_team_id=ExternalId("team-home"),
        away_team_id=ExternalId("team-away"),
        scheduled_at=datetime(2026, 2, 1, 18, 30),
    )
    match.score_summary = ScoreSummary(
        home_score=80,
        away_score=77,
        periods=(PeriodScore(period=1, home=40, away=38), PeriodScore(period=2, home=40, away=39)),
    )
    match.home_team_stats = TeamStats(
        team_external_id="team-home",
        points_for=80,
        points_against=77,
        field_goals_made=30,
        field_goals_attempted=60,
        three_points_made=8,
        three_points_attempted=20,
        free_throws_made=12,
        free_throws_attempted=16,
        turnovers=10,
        rebounds=38,
    )
    match.away_team_stats = TeamStats(
        team_external_id="team-away",
        points_for=77,
        points_against=80,
        field_goals_made=28,
        field_goals_attempted=62,
        three_points_made=7,
        three_points_attempted=18,
        free_throws_made=14,
        free_throws_attempted=18,
        turnovers=12,
        rebounds=34,
    )
    match.player_stats = (
        PlayerStats(
            player_external_id="pl-1",
            team_external_id="team-home",
            points=22,
            rebounds=9,
            assists=5,
        ),
    )
    match.finalize(finalized_at=datetime(2026, 2, 1, 20, 0), actor_id="admin-1")
    match_repo.save(match)

    handler = GenerateStandingSnapshotHandler(InMemoryStandingRepository(), match_repo)
    command = GenerateStandingSnapshotCommand(
        command_id=str(uuid4()),
        meta=CommandMeta(version="1.0", issued_at=datetime.utcnow()),
        actor=Actor(id="admin-1", role="admin"),
        payload={"competition_id": "feb-competition", "season_code": "2025-2026", "as_of": "2026-02-01T23:59:59Z", "rules_version": "rules-v1"},
    )

    event = handler.handle(command)
    assert event.payload["matches_included_count"] == 1


def test_register_player_to_squad_handler():
    player_repo = InMemoryPlayerRepository()
    team_repo = InMemoryTeamRepository()
    player = Player(
        external_id=ExternalId("pl-987"),
        player_id=PlayerId(str(uuid4())),
        name="Juan Perez",
    )
    team = Team(
        external_id=ExternalId("team-123"),
        team_id=TeamId(str(uuid4())),
        name="Club Basket",
    )
    player_repo.save(player)
    team_repo.save(team)

    handler = RegisterPlayerToSquadHandler(player_repo, team_repo)
    command = RegisterPlayerToSquadCommand(
        command_id=str(uuid4()),
        meta=CommandMeta(version="1.0", issued_at=datetime.utcnow()),
        actor=Actor(id="admin-1", role="admin"),
        payload={
            "player_external_id": "pl-987",
            "team_external_id": "team-123",
            "season_code": "2025-2026",
            "dorsal": "12",
            "registered_from": "2025-08-01T00:00:00Z",
        },
    )

    event = handler.handle(command)
    assert event.payload["player_external_id"] == "pl-987"


@pytest.mark.parametrize(
    "category,min_games,top_n",
    [
        ("points_per_game", 3, 5),
        ("rebounds", 0, 10),
    ],
)
def test_generate_leaderboard_handler(category, min_games, top_n):
    from feb_score.application.use_cases.handlers import GenerateLeaderboardHandler

    handler = GenerateLeaderboardHandler(InMemoryMatchRepository())
    command = GenerateLeaderboardCommand(
        command_id=str(uuid4()),
        meta=CommandMeta(version="1.0", issued_at=datetime.utcnow()),
        actor=Actor(id="system-analytics", role="system"),
        payload={"season_code": "2025-2026", "category": category, "min_games": min_games, "top_n": top_n},
    )

    event = handler.handle(command)
    assert event.payload["category"] == category
    assert event.payload["entries_count"] == 0
