from datetime import datetime
from uuid import uuid4

import pytest

from feb_score.application.commands.commands import RegisterPlayerToSquadCommand
from feb_score.application.repositories.in_memory import InMemoryPlayerRepository, InMemoryTeamRepository
from feb_score.application.use_cases.handlers import RegisterPlayerToSquadHandler
from feb_score.domain.player.model import Player, PlayerRegistration
from feb_score.domain.team.model import Team, TeamPlayerRegistration
from feb_score.domain.errors import InvalidPlayerRegistration
from feb_score.domain.value_objects import Actor, CommandMeta, ExternalId, PlayerId, SeasonCode, TeamId


def test_register_player_to_team():
    player = Player(
        external_id=ExternalId("pl-987"),
        player_id=PlayerId("3fa85f64-5717-4562-b3fc-2c963f66afa6"),
        name="Juan Perez",
    )
    team = Team(
        external_id=ExternalId("team-123"),
        team_id=TeamId("4fa85f64-5717-4562-b3fc-2c963f66afa7"),
        name="Club Basket",
    )

    season_code = SeasonCode("2025-2026")
    registered_at = datetime(2025, 8, 1).date()
    player.register_for_team(
        team_external_id=str(team.external_id),
        season_code=season_code,
        dorsal=12,
        registered_at=registered_at,
    )
    team.add_player_registration(
        player_external_id=str(player.external_id),
        season_code=season_code,
        dorsal=12,
    )

    assert player.is_registered_for(str(team.external_id), season_code)
    assert team.has_player(str(player.external_id), season_code)


def test_prevent_duplicate_registration():
    player = Player(
        external_id=ExternalId("pl-987"),
        player_id=PlayerId("3fa85f64-5717-4562-b3fc-2c963f66afa6"),
        name="Juan Perez",
    )
    season_code = SeasonCode("2025-2026")
    player.register_for_team(
        team_external_id="team-123",
        season_code=season_code,
        dorsal=12,
        registered_at=datetime(2025, 8, 1).date(),
    )
    with pytest.raises(InvalidPlayerRegistration):
        player.register_for_team(
            team_external_id="team-123",
            season_code=season_code,
            dorsal=12,
            registered_at=datetime(2025, 8, 2).date(),
        )


def test_player_registration_value_object_validation():
    with pytest.raises(ValueError, match="team_external_id"):
        PlayerRegistration(team_external_id="", season_code=SeasonCode("2025-2026"))

    with pytest.raises(ValueError, match="dorsal"):
        PlayerRegistration(team_external_id="team-123", season_code=SeasonCode("2025-2026"), dorsal=-1)


def test_team_registration_value_object_validation():
    with pytest.raises(ValueError, match="player_external_id"):
        TeamPlayerRegistration(player_external_id="", season_code=SeasonCode("2025-2026"))

    with pytest.raises(ValueError, match="dorsal"):
        TeamPlayerRegistration(player_external_id="pl-1", season_code=SeasonCode("2025-2026"), dorsal=-1)


def test_team_prevents_duplicate_player_registration():
    team = Team(
        external_id=ExternalId("team-123"),
        team_id=TeamId("4fa85f64-5717-4562-b3fc-2c963f66afa7"),
        name="Club Basket",
    )
    season_code = SeasonCode("2025-2026")
    team.add_player_registration(player_external_id="pl-987", season_code=season_code, dorsal=12)

    with pytest.raises(InvalidPlayerRegistration):
        team.add_player_registration(player_external_id="pl-987", season_code=season_code, dorsal=13)


def test_register_player_to_squad_handler_is_atomic_when_team_rejects_duplicate():
    player_repo = InMemoryPlayerRepository()
    team_repo = InMemoryTeamRepository()
    player = Player(
        external_id=ExternalId("pl-987"),
        player_id=PlayerId("3fa85f64-5717-4562-b3fc-2c963f66afa6"),
        name="Juan Perez",
    )
    team = Team(
        external_id=ExternalId("team-123"),
        team_id=TeamId("4fa85f64-5717-4562-b3fc-2c963f66afa7"),
        name="Club Basket",
    )
    season_code = SeasonCode("2025-2026")
    team.add_player_registration(player_external_id="pl-987", season_code=season_code, dorsal=12)
    player_repo.save(player)
    team_repo.save(team)

    command = RegisterPlayerToSquadCommand(
        command_id=str(uuid4()),
        meta=CommandMeta(version="1.0", issued_at=datetime.utcnow()),
        actor=Actor(id="admin-1", role="admin"),
        payload={
            "player_external_id": "pl-987",
            "team_external_id": "team-123",
            "season_code": "2025-2026",
            "dorsal": "13",
            "registered_from": "2025-08-02T00:00:00Z",
        },
    )

    with pytest.raises(InvalidPlayerRegistration):
        RegisterPlayerToSquadHandler(player_repo, team_repo).handle(command)

    stored_player = player_repo.get_by_external_id(ExternalId("pl-987"))
    stored_team = team_repo.get_by_external_id(ExternalId("team-123"))

    assert stored_player.registrations == []
    assert len(stored_team.registrations) == 1
    assert stored_team.registrations[0].dorsal == 12
    assert not hasattr(stored_player, "version")
    assert not hasattr(stored_team, "version")
    assert not hasattr(stored_player, "history")
    assert not hasattr(stored_team, "history")
    assert stored_player.collect_events() == []
    assert stored_team.collect_events() == []


def test_register_player_to_squad_handler_success_updates_both_aggregates_and_emits_event():
    player_repo = InMemoryPlayerRepository()
    team_repo = InMemoryTeamRepository()
    player = Player(
        external_id=ExternalId("pl-987"),
        player_id=PlayerId("3fa85f64-5717-4562-b3fc-2c963f66afa6"),
        name="Juan Perez",
    )
    team = Team(
        external_id=ExternalId("team-123"),
        team_id=TeamId("4fa85f64-5717-4562-b3fc-2c963f66afa7"),
        name="Club Basket",
    )
    player_repo.save(player)
    team_repo.save(team)

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
    stored_player = player_repo.get_by_external_id(ExternalId("pl-987"))
    stored_team = team_repo.get_by_external_id(ExternalId("team-123"))

    assert stored_player.is_registered_for("team-123", SeasonCode("2025-2026"))
    assert stored_team.has_player("pl-987", SeasonCode("2025-2026"))
    assert stored_player.registrations[0].dorsal == 12
    assert stored_team.registrations[0].dorsal == 12
    assert event.__class__.__name__ == "PlayerRegistered"
    assert event.payload["player_external_id"] == "pl-987"
    assert event.payload["team_external_id"] == "team-123"


def test_register_player_to_squad_handler_rejects_duplicate_without_second_mutation():
    player_repo = InMemoryPlayerRepository()
    team_repo = InMemoryTeamRepository()
    player = Player(
        external_id=ExternalId("pl-987"),
        player_id=PlayerId("3fa85f64-5717-4562-b3fc-2c963f66afa6"),
        name="Juan Perez",
    )
    team = Team(
        external_id=ExternalId("team-123"),
        team_id=TeamId("4fa85f64-5717-4562-b3fc-2c963f66afa7"),
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

    first_event = handler.handle(command)
    player.clear_events()
    team.clear_events()

    with pytest.raises(InvalidPlayerRegistration):
        handler.handle(command)

    assert first_event.__class__.__name__ == "PlayerRegistered"
    assert len(player.registrations) == 1
    assert len(team.registrations) == 1
    assert player.registrations[0].dorsal == 12
    assert team.registrations[0].dorsal == 12
    assert player.collect_events() == []
    assert team.collect_events() == []
