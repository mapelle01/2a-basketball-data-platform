import json
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from pathlib import Path
from uuid import uuid4

import pytest
import jsonschema
from jsonschema import FormatChecker

from feb_score.application.commands.commands import (
    CreateOrUpdateMatchCommand,
    ProposeCorrectionCommand,
    RegisterPlayerToSquadCommand,
)
from feb_score.application.repositories.in_memory import InMemoryPlayerRepository, InMemoryTeamRepository
from feb_score.application.use_cases.handlers import RegisterPlayerToSquadHandler
from feb_score.domain.match.model import Match
from feb_score.domain.player.model import Player
from feb_score.domain.publication.model import Publication
from feb_score.domain.team.model import Team
from feb_score.domain.value_objects import (
    Actor,
    CommandMeta,
    CompetitionId,
    ExternalId,
    MatchId,
    PeriodScore,
    PlayerId,
    PublicationId,
    RatingVersion,
    SeasonCode,
    ScoreSummary,
    TeamId,
)

ROOT = Path(__file__).resolve().parents[2]


def to_primitive(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if is_dataclass(value):
        return {k: to_primitive(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {k: to_primitive(v) for k, v in value.items()}
    if isinstance(value, list):
        return [to_primitive(v) for v in value]
    return value


def load_schema(name: str) -> dict:
    path = ROOT / name
    return json.loads(path.read_text())


def validate_schema(instance: object, schema_path: str) -> None:
    schema = load_schema(schema_path)
    jsonschema.validate(to_primitive(instance), schema, format_checker=FormatChecker())


def test_create_or_update_match_command_matches_schema():
    command = CreateOrUpdateMatchCommand(
        command_id=str(MatchId(str(uuid4()))),
        meta=CommandMeta(version="1.0", issued_at=datetime.utcnow()),
        actor=Actor(id="system-1", role="system"),
        payload={
            "external_id": "2513600",
            "competition_id": "feb-competition",
            "season_code": "2025-2026",
            "round_number": 5,
            "scheduled_at": "2026-02-01T18:30:00Z",
            "home_team": {"external_id": "team-home", "name": "Home"},
            "away_team": {"external_id": "team-away", "name": "Away"},
            "source": {"id": "feb-api", "fetched_at": "2026-02-01T18:00:00Z"},
        },
    )
    validate_schema(command, "contracts/commands/create_or_update_match.v1.json")


def test_propose_correction_command_matches_schema():
    command = ProposeCorrectionCommand(
        command_id=str(MatchId(str(uuid4()))),
        meta=CommandMeta(version="1.0", issued_at=datetime.utcnow()),
        actor=Actor(id="editor-1", role="editor"),
        payload={
            "match_external_id": "2513600",
            "proposed_by": {"id": "editor-1", "role": "editor"},
            "reason": "Correction",
            "changes": [{"op": "update_score", "home_score": 78, "away_score": 75}],
        },
    )
    validate_schema(command, "contracts/commands/propose_correction.v1.json")


def test_match_finalized_event_matches_schema():
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
    match.score_summary = ScoreSummary(
        home_score=78,
        away_score=75,
        periods=(PeriodScore(period=1, home=40, away=35), PeriodScore(period=2, home=38, away=40)),
    )
    from feb_score.domain.statistics.model import TeamStats

    match.home_team_stats = TeamStats(
        team_external_id="team-home",
        points_for=78,
        points_against=75,
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
        points_for=75,
        points_against=78,
        field_goals_made=28,
        field_goals_attempted=62,
        three_points_made=7,
        three_points_attempted=18,
        free_throws_made=13,
        free_throws_attempted=15,
        turnovers=12,
        rebounds=34,
    )
    match.player_stats = ()
    match.finalize(finalized_at=datetime.utcnow(), actor_id="admin-1")
    finalized_event = match.collect_events()[-1]
    validate_schema(finalized_event, "contracts/events/match_finalized.v1.json")


def test_publication_created_event_matches_schema():
    publication = Publication(
        publication_id=PublicationId(str(uuid4())),
        title="Match summary",
        content="Summary content",
        template_id="tpl-summary-v1",
        references=[{"type": "match", "id": "2513600"}],
    )
    publication.create(creator=Actor(id="editor-1", role="editor"), created_at=datetime.utcnow())
    event = publication.collect_events()[0]
    validate_schema(event, "contracts/events/publication_created.v1.json")


def test_player_registered_event_from_handler_matches_schema():
    player_repo = InMemoryPlayerRepository()
    team_repo = InMemoryTeamRepository()
    player_repo.save(
        Player(
            external_id=ExternalId("pl-987"),
            player_id=PlayerId(str(uuid4())),
            name="Juan Perez",
        )
    )
    team_repo.save(
        Team(
            external_id=ExternalId("team-123"),
            team_id=TeamId(str(uuid4())),
            name="Club Basket",
        )
    )
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

    event = RegisterPlayerToSquadHandler(player_repo, team_repo).handle(command)

    validate_schema(event, "contracts/events/player_registered.v1.json")


def test_validation_examples_against_contracts():
    mapping = {
        "valid_create_or_update_match.json": "contracts/commands/create_or_update_match.v1.json",
        "invalid_create_or_update_match.json": "contracts/commands/create_or_update_match.v1.json",
        "correction_example.json": "contracts/commands/propose_correction.v1.json",
        "idempotency_example.json": "contracts/commands/create_or_update_match.v1.json",
        "match_finalized_example.json": "contracts/events/match_finalized.v1.json",
    }

    for file_name, schema_path in mapping.items():
        data = json.loads((ROOT / "validation_examples" / file_name).read_text())
        if file_name.startswith("invalid"):
            with pytest.raises(jsonschema.ValidationError):
                jsonschema.validate(data, load_schema(schema_path), format_checker=FormatChecker())
        else:
            jsonschema.validate(data, load_schema(schema_path), format_checker=FormatChecker())
