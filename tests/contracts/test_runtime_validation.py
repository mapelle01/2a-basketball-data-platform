"""FASE 5 — GRUPO 4: runtime command validation via the contract_validated decorator.

Verifies that handlers reject schema-invalid commands BEFORE touching domain state
and accept schema-valid ones. Run: python3 -m pytest tests/contracts/test_runtime_validation.py -q
"""

from datetime import datetime
from uuid import uuid4

import pytest

from feb_score.application.commands.commands import CreateOrUpdateMatchCommand, RegisterPlayerToSquadCommand
from feb_score.application.repositories.in_memory import (
    InMemoryMatchRepository,
    InMemoryPlayerRepository,
    InMemoryTeamRepository,
)
from feb_score.application.use_cases.handlers import CreateOrUpdateMatchHandler, RegisterPlayerToSquadHandler
from feb_score.application.validation import ContractValidationError
from feb_score.domain.player.model import Player
from feb_score.domain.team.model import Team
from feb_score.domain.value_objects import Actor, CommandMeta, ExternalId, PlayerId, TeamId


def base_match_payload():
    return {
        "external_id": "2513600",
        "competition_id": "feb-competition",
        "season_code": "2025-2026",
        "round_number": 5,
        "scheduled_at": "2026-02-01T18:30:00Z",
        "home_team": {"external_id": "team-home", "name": "Home"},
        "away_team": {"external_id": "team-away", "name": "Away"},
        "source": {"id": "feb-api", "fetched_at": "2026-02-01T18:00:00Z", "s3_path": "s3://x"},
    }


def match_command(payload):
    return CreateOrUpdateMatchCommand(
        command_id=str(uuid4()),
        meta=CommandMeta(version="1.0", issued_at=datetime.utcnow()),
        actor=Actor(id="system-1", role="system"),
        payload=payload,
    )


def test_valid_command_accepted():
    handler = CreateOrUpdateMatchHandler(InMemoryMatchRepository())
    events = handler.handle(match_command(base_match_payload()))
    assert len(events) == 1


def test_invalid_command_id_rejected():
    handler = CreateOrUpdateMatchHandler(InMemoryMatchRepository())
    command = match_command(base_match_payload())
    command = CreateOrUpdateMatchCommand(
        command_id="not-a-uuid",
        meta=command.meta,
        actor=command.actor,
        payload=command.payload,
    )
    with pytest.raises(ContractValidationError):
        handler.handle(command)


def test_missing_required_field_rejected():
    payload = base_match_payload()
    del payload["scheduled_at"]
    handler = CreateOrUpdateMatchHandler(InMemoryMatchRepository())
    with pytest.raises(ContractValidationError):
        handler.handle(match_command(payload))


def test_unknown_field_rejected():
    payload = base_match_payload()
    payload["unknown_field"] = True
    handler = CreateOrUpdateMatchHandler(InMemoryMatchRepository())
    with pytest.raises(ContractValidationError):
        handler.handle(match_command(payload))


def test_wrong_type_rejected():
    payload = base_match_payload()
    payload["scheduled_at"] = 42
    handler = CreateOrUpdateMatchHandler(InMemoryMatchRepository())
    with pytest.raises(ContractValidationError):
        handler.handle(match_command(payload))


def test_invalid_enum_rejected():
    from feb_score.application.commands.commands import BackfillSeasonCommand
    from feb_score.application.repositories.in_memory import InMemoryCompetitionRepository
    from feb_score.application.use_cases.handlers import BackfillSeasonHandler

    command = BackfillSeasonCommand(
        command_id=str(uuid4()),
        meta=CommandMeta(version="1.0", issued_at=datetime.utcnow()),
        actor=Actor(id="admin-1", role="admin"),
        payload={"season_code": "2025-2026", "from_round": 1, "to_round": 38, "bad_field": "x"},
    )
    with pytest.raises(ContractValidationError):
        BackfillSeasonHandler(InMemoryCompetitionRepository()).handle(command)


def test_player_registered_emits_registration_id_and_dorsal():
    player_repo = InMemoryPlayerRepository()
    team_repo = InMemoryTeamRepository()
    player_repo.save(Player(external_id=ExternalId("pl-987"), player_id=PlayerId(str(uuid4())), name="Juan"))
    team_repo.save(Team(external_id=ExternalId("team-123"), team_id=TeamId(str(uuid4())), name="Club"))

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
            "registered_to": "2026-06-30T23:59:59Z",
            "role": "player",
        },
    )
    event = RegisterPlayerToSquadHandler(player_repo, team_repo).handle(command)
    assert event.payload["registration_id"]
    assert event.payload["dorsal"] == "12"