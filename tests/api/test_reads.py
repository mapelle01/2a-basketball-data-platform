"""FASE 11 — Read side (minimal projections, interface-backed, no business logic)."""

from datetime import datetime
from uuid import uuid4

from feb_score.domain.correction.model import CorrectionProposal
from feb_score.domain.leaderboard.model import Leaderboard
from feb_score.domain.value_objects import (
    Actor,
    CompetitionId,
    CorrectionProposalId,
    ExternalId,
    LeaderboardId,
    MatchId,
    PlayerId,
    SeasonCode,
    TeamId,
)
from feb_score.domain.player.model import Player
from feb_score.domain.team.model import Team
from feb_score.infrastructure.persistence.connection import SqliteDatabase
from feb_score.infrastructure.persistence.repositories import (
    SqliteCompetitionRepository,
    SqliteCorrectionRepository,
    SqliteLeaderboardRepository,
    SqliteMatchRepository,
    SqlitePlayerRepository,
    SqliteTeamRepository,
)

from api_helpers import create_payload, ready_to_finalize


def test_read_match_dto(client):
    assert client.post("/v1/commands/create_or_update_match",
                       json={"payload": create_payload()}).status_code == 200
    dto = client.get("/v1/matches/2513600").json()
    assert dto["status"] == "SCHEDULED"
    assert dto["home_team_id"] == "team-home"
    assert dto["round_number"] == 5
    assert dto["scheduled_at"] == "2026-02-01T18:30:00"


def test_read_missing_match_returns_404(client):
    assert client.get("/v1/matches/does-not-exist").status_code == 404


def test_read_player_dto(client, db_path):
    db = SqliteDatabase(db_path)
    SqlitePlayerRepository(db).save(Player(external_id=ExternalId("pl-1"), player_id=PlayerId(str(uuid4())), name="Juan"))
    dto = client.get("/v1/players/pl-1").json()
    assert dto["external_id"] == "pl-1" and dto["name"] == "Juan"
    assert dto["registrations_count"] == 0
    # Bio is exposed so a backfill is verifiable from outside; absent stays null.
    assert dto["position"] is None and dto["height_cm"] is None
    assert dto["birth_date"] is None and dto["nationality"] is None
    assert client.get("/v1/players/nope").status_code == 404


def test_read_player_dto_exposes_bio_when_present(client, db_path):
    from datetime import date

    SqlitePlayerRepository(SqliteDatabase(db_path)).save(Player(
        external_id=ExternalId("pl-2"), player_id=PlayerId(str(uuid4())), name="Jordi",
        position="Alero", height_cm=196, nationality="ESPAÑA",
        birth_date=date(1998, 4, 11), birth_place="Barcelona"))
    dto = client.get("/v1/players/pl-2").json()
    assert dto["position"] == "Alero" and dto["height_cm"] == 196
    assert dto["birth_date"] == "1998-04-11" and dto["birth_place"] == "Barcelona"
    assert dto["nationality"] == "ESPAÑA"


def test_read_team_dto(client, db_path):
    db = SqliteDatabase(db_path)
    SqliteTeamRepository(db).save(Team(external_id=ExternalId("t-1"), team_id=TeamId(str(uuid4())), name="Club"))
    assert client.get("/v1/teams/t-1").json()["name"] == "Club"
    assert client.get("/v1/teams/nope").status_code == 404


def test_read_competition_dto(client, db_path):
    from feb_score.domain.competition.model import Competition

    db = SqliteDatabase(db_path)
    comp = Competition(external_id=ExternalId("feb-comp"), competition_id=CompetitionId(str(uuid4())), name="League")
    comp.define_season(SeasonCode("2025-2026"), rules_version="rules-v1")
    SqliteCompetitionRepository(db).save(comp)
    dto = client.get("/v1/competitions/feb-comp").json()
    assert dto["name"] == "League"
    assert dto["seasons"] == ["2025-2026"]
    assert client.get("/v1/competitions/nope").status_code == 404


def test_read_correction_proposal_dto(client, db_path):
    db = SqliteDatabase(db_path)
    proposal = CorrectionProposal(
        proposal_id=CorrectionProposalId(str(uuid4())),
        match_external_id=ExternalId("2513600"),
        proposed_by=Actor(id="editor-1", role="editor"),
        proposed_at=datetime(2026, 2, 2, 10, 0),
        reason="official",
        changes=[{"op": "update_score", "home_score": 80, "away_score": 77}],
    )
    SqliteCorrectionRepository(db).save(proposal)
    dto = client.get(f"/v1/correction-proposals/{proposal.proposal_id.value}").json()
    assert dto["status"] == "PROPOSED"
    assert dto["match_external_id"] == "2513600"


def test_read_leaderboard_dto(client, db_path):
    db = SqliteDatabase(db_path)
    SqliteMatchRepository(db).save(ready_to_finalize())
    assert client.post("/v1/commands/finalize_match",
                       json={"payload": {"match_external_id": "2513600"}}).status_code == 200
    assert client.post("/v1/commands/generate_leaderboard", json={"payload": {
        "season_code": "2025-2026", "category": "points_per_game",
        "min_games": 0, "top_n": 10, "competition_id": "feb-comp",
    }}).status_code == 200

    leaderboard_id = str(SqliteLeaderboardRepository(db).list_all()[0].leaderboard_id)
    dto = client.get(f"/v1/leaderboards/{leaderboard_id}").json()
    assert dto["entries"][0]["player_external_id"] == "pl-1"
    assert dto["entries"][0]["value"] == 22.0
    assert client.get("/v1/leaderboards/nope").status_code == 404