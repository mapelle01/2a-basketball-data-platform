from datetime import datetime
from uuid import uuid4

import pytest

from feb_score.application.commands.commands import (
    ApproveCorrectionCommand,
    BackfillSeasonCommand,
    ComputePlayerRatingCommand,
    CreateOrUpdateMatchCommand,
    CreatePublicationCommand,
    GenerateStandingSnapshotCommand,
    ProposeCorrectionCommand,
)
from feb_score.application.repositories.in_memory import (
    InMemoryCompetitionRepository,
    InMemoryCorrectionRepository,
    InMemoryIdempotencyRepository,
    InMemoryMatchRepository,
    InMemoryPlayerRepository,
    InMemoryPublicationRepository,
    InMemoryRatingRepository,
    InMemoryStandingRepository,
    InMemoryTeamRepository,
)
from feb_score.application.use_cases.handlers import (
    ApproveCorrectionHandler,
    BackfillSeasonHandler,
    ComputePlayerRatingHandler,
    CreateOrUpdateMatchHandler,
    CreatePublicationHandler,
    GenerateStandingSnapshotHandler,
    ProposeCorrectionHandler,
    RegisterPlayerToSquadHandler,
)
from feb_score.domain.correction.model import CorrectionProposal
from feb_score.domain.match.model import Match
from feb_score.domain.player.model import Player
from feb_score.domain.publication.model import Publication
from feb_score.domain.ratings.model import PlayerRating
from feb_score.domain.statistics.model import PlayerStats, TeamStats
from feb_score.domain.team.model import Team
from feb_score.domain.value_objects import (
    Actor,
    CommandMeta,
    CompetitionId,
    ExternalId,
    MatchId,
    PublicationId,
    RatingVersion,
    SeasonCode,
    TeamId,
)


def test_finalize_match_handler_idempotent():
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
    match.score_summary = None
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
    from feb_score.domain.value_objects import PeriodScore, ScoreSummary

    match.score_summary = ScoreSummary(
        home_score=80,
        away_score=77,
        periods=(PeriodScore(period=1, home=40, away=38), PeriodScore(period=2, home=40, away=39)),
    )
    match.finalize(finalized_at=datetime.utcnow(), actor_id="admin-1")
    match_repo.save(match)

    idempotency_repo = InMemoryIdempotencyRepository()
    handler = GenerateStandingSnapshotHandler(InMemoryStandingRepository(), match_repo, idempotency_repo)
    command_id = str(uuid4())
    command = GenerateStandingSnapshotCommand(
        command_id=command_id,
        meta=CommandMeta(version="1.0", issued_at=datetime.utcnow()),
        actor=Actor(id="admin-1", role="admin"),
        payload={"competition_id": "feb-competition", "season_code": "2025-2026", "as_of": "2026-02-01T23:59:59Z", "rules_version": "rules-v1"},
    )

    first_result = handler.handle(command)
    second_result = handler.handle(command)

    assert first_result.payload["matches_included_count"] == 1
    assert second_result == []


def test_propose_correction_idempotency():
    correction_repo = InMemoryCorrectionRepository()
    idempotency_repo = InMemoryIdempotencyRepository()
    handler = ProposeCorrectionHandler(correction_repo, idempotency_repo)

    command = ProposeCorrectionCommand(
        command_id=str(uuid4()),
        meta=CommandMeta(version="1.0", issued_at=datetime.utcnow()),
        actor=Actor(id="editor-1", role="editor"),
        payload={
            "match_external_id": "2513600",
            "proposed_by": {"id": "editor-1", "role": "editor"},
            "reason": "Score correction",
            "changes": [{"op": "update_score", "home_score": 78, "away_score": 75}],
        },
    )

    first_result = handler.handle(command)
    second_result = handler.handle(command)

    assert first_result.payload["proposal_id"] == command.command_id
    assert second_result == []


def test_create_publication_handler_records_publication_event():
    publication_repo = InMemoryPublicationRepository()
    handler = CreatePublicationHandler(publication_repo)
    command = CreatePublicationCommand(
        command_id=str(uuid4()),
        meta=CommandMeta(version="1.0", issued_at=datetime.utcnow()),
        actor=Actor(id="editor-1", role="editor"),
        payload={
            "template_id": "tpl-match-summary-v1",
            "payload_refs": {"match_external_id": "2513600"},
            "scheduled_at": "2026-02-02T08:00:00Z",
        },
    )

    events = handler.handle(command)
    assert len(events) == 1
    assert events[0].payload["status"] == "DRAFT"
    assert publication_repo._publications[0].status == "DRAFT"


def test_compute_player_rating_handler_emits_milestone():
    match_repo = InMemoryMatchRepository()
    rating_repo = InMemoryRatingRepository()
    handler = ComputePlayerRatingHandler(match_repo, rating_repo)
    match = Match(
        external_id=ExternalId("2513600"),
        match_id=MatchId(str(uuid4())),
        competition_id=CompetitionId("unknown"),
        season_code=SeasonCode("2025-2026"),
        round_number=1,
        home_team_id=ExternalId("team-home"),
        away_team_id=ExternalId("team-away"),
        scheduled_at=datetime(2026, 2, 1, 18, 30),
    )
    player_stat = PlayerStats(
        player_external_id="pl-1",
        team_external_id="team-home",
        points=100,
        rebounds=30,
        assists=20,
        turnovers=5,
    )
    match.player_stats = (player_stat,)
    match_repo.save(match)

    command = ComputePlayerRatingCommand(
        command_id=str(uuid4()),
        meta=CommandMeta(version="1.0", issued_at=datetime.utcnow()),
        actor=Actor(id="system-1", role="system"),
        payload={"player_external_id": "pl-1", "season_code": "2025-2026", "rating_version": "v1.0"},
    )

    events = handler.handle(command)
    assert any(event.__class__.__name__ == "PlayerRatingComputed" for event in events)
    assert any(event.__class__.__name__ == "PlayerMilestoneReached" for event in events)


def test_compute_player_rating_scoped_by_competition_id():
    from feb_score.domain.errors import InvalidRatingCalculation

    match_repo = InMemoryMatchRepository()
    rating_repo = InMemoryRatingRepository()
    match = Match(
        external_id=ExternalId("2513600"),
        match_id=MatchId(str(uuid4())),
        competition_id=CompetitionId("feb-competition"),
        season_code=SeasonCode("2025-2026"),
        round_number=1,
        home_team_id=ExternalId("team-home"),
        away_team_id=ExternalId("team-away"),
        scheduled_at=datetime(2026, 2, 1, 18, 30),
    )
    match.player_stats = (
        PlayerStats(player_external_id="pl-1", team_external_id="team-home", points=30, rebounds=10, assists=5, turnovers=2),
    )
    match_repo.save(match)

    handler = ComputePlayerRatingHandler(match_repo, rating_repo)
    with_competition = ComputePlayerRatingCommand(
        command_id=str(uuid4()),
        meta=CommandMeta(version="1.0", issued_at=datetime.utcnow()),
        actor=Actor(id="system-1", role="system"),
        payload={"competition_id": "feb-competition", "player_external_id": "pl-1", "season_code": "2025-2026", "rating_version": "v1.0"},
    )
    events = handler.handle(with_competition)
    assert any(e.__class__.__name__ == "PlayerRatingComputed" for e in events)

    without_competition = ComputePlayerRatingCommand(
        command_id=str(uuid4()),
        meta=CommandMeta(version="1.0", issued_at=datetime.utcnow()),
        actor=Actor(id="system-1", role="system"),
        payload={"player_external_id": "pl-1", "season_code": "2025-2026", "rating_version": "v1.0"},
    )
    with pytest.raises(InvalidRatingCalculation):
        handler.handle(without_competition)


def test_compute_player_rating_is_idempotent():
    from feb_score.application.use_cases.handlers import ComputePlayerRatingHandler

    match_repo = InMemoryMatchRepository()
    rating_repo = InMemoryRatingRepository()
    idempotency_repo = InMemoryIdempotencyRepository()
    match = Match(
        external_id=ExternalId("2513600"),
        match_id=MatchId(str(uuid4())),
        competition_id=CompetitionId("unknown"),
        season_code=SeasonCode("2025-2026"),
        round_number=1,
        home_team_id=ExternalId("team-home"),
        away_team_id=ExternalId("team-away"),
        scheduled_at=datetime(2026, 2, 1, 18, 30),
    )
    match.player_stats = (
        PlayerStats(player_external_id="pl-1", team_external_id="team-home", points=30, rebounds=10, assists=5, turnovers=2),
    )
    match_repo.save(match)

    handler = ComputePlayerRatingHandler(match_repo, rating_repo, idempotency_repo)
    command = ComputePlayerRatingCommand(
        command_id=str(uuid4()),
        meta=CommandMeta(version="1.0", issued_at=datetime.utcnow()),
        actor=Actor(id="system-1", role="system"),
        payload={"player_external_id": "pl-1", "season_code": "2025-2026", "rating_version": "v1.0"},
    )

    first = handler.handle(command)
    second = handler.handle(command)
    assert any(e.__class__.__name__ == "PlayerRatingComputed" for e in first)
    assert second == []
    assert len(rating_repo._ratings) == 1


def test_backfill_season_handler_emits_started_and_completed():
    competition_repo = InMemoryCompetitionRepository()
    competition = None
    from feb_score.domain.competition.model import Competition

    competition = Competition(
        external_id=ExternalId("comp-1"),
        competition_id=CompetitionId(str(uuid4())),
        name="FEB League",
    )
    competition.define_season(SeasonCode("2025-2026"), rules_version="rules-v1")
    competition_repo.save(competition)

    handler = BackfillSeasonHandler(competition_repo)
    command = BackfillSeasonCommand(
        command_id=str(uuid4()),
        meta=CommandMeta(version="1.0", issued_at=datetime.utcnow()),
        actor=Actor(id="admin-1", role="admin"),
        payload={"competition_id": "comp-1", "season_code": "2025-2026", "from_round": 1, "to_round": 5},
    )

    events = handler.handle(command)
    assert len(events) == 2
    assert events[0].payload["request_id"] == events[1].payload["request_id"]
    assert events[1].payload["status"] == "ok"
