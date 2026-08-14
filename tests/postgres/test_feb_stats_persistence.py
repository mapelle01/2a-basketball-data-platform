"""FASE 21.B3 — persistence of real FEB BoxScore team/player stats.

Covers both backends (SQLite + PostgreSQL via the ``backend`` fixture):
parse fixture -> upsert_match_stats command -> UpsertMatchStatsHandler ->
Match aggregate holds stats AND the indexed projection is written idempotently
(match_external_id + player_external_id UNIQUE).
"""
from __future__ import annotations

import importlib.util
import json
from datetime import datetime
from pathlib import Path

import pytest

from feb_score.application.use_cases.handlers import UpsertMatchStatsHandler
from feb_score.application.commands.commands import UpsertMatchStatsCommand
from feb_score.domain.value_objects import Actor, CommandMeta, ExternalId, MatchId
from feb_score.domain.match.model import Match
from feb_score.domain.competition.model import Competition
from feb_score.domain.value_objects import CompetitionId, SeasonCode
from feb_score.domain.statistics.model import PlayerStats, TeamStats

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = json.loads((ROOT / "tests/ingestion/fixtures/boxscore_2486864.json").read_text())

_spec = importlib.util.spec_from_file_location(
    "ingest_match_b3", ROOT / "scripts" / "feb" / "ingest_match.py"
)
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)

SEASON = "2025-2026"
MATCH_ID = "2486864"


def _parsed():
    return M.parse_boxscore(FIXTURE, match_id=MATCH_ID, season_code=SEASON)


def _match(external_id: str = MATCH_ID, season: str = SEASON) -> Match:
    return Match(
        external_id=ExternalId(external_id),
        match_id=MatchId("4903981f-1268-49ab-bf4a-56f24255125c"),
        competition_id=CompetitionId("segunda-feb"),
        season_code=SeasonCode(season),
        round_number=1,
        home_team_id=ExternalId("979897"),
        away_team_id=ExternalId("981281"),
        scheduled_at=datetime(2025, 10, 18, 19, 0),
    )


def _command(parsed, command_id="11111111-1111-1111-1111-111111111111"):
    raw = M.to_stats_command(parsed, "segunda-feb")
    return _stats_command(raw["payload"], command_id=command_id)


def _stats_command(payload, command_id="00000000-0000-0000-0000-000000000000"):
    return UpsertMatchStatsCommand(
        command_id=command_id,
        meta=CommandMeta(version="1.0", issued_at=datetime(2026, 2, 1, 20, 0)),
        actor=Actor(id="ingestor-1", role="system"),
        payload=payload,
    )


@pytest.fixture
def db(backend):
    return backend.make_db()


@pytest.fixture
def match_repo(backend, db):
    return backend.repo(db, "match")


@pytest.fixture
def stats_repo(backend, db):
    return backend.repo(db, "stats")


@pytest.fixture
def idem_repo(backend, db):
    return backend.repo(db, "idempotency")


def _handler(match_repo, stats_repo, idem_repo):
    return UpsertMatchStatsHandler(match_repo, stats_repo, idem_repo)


# --- 1. parse all fields (player + team stats)
def test_parse_fixture_has_team_and_player_stats():
    parsed = _parsed()
    assert len(parsed["stats"]["home"]) == 10
    assert len(parsed["stats"]["away"]) == 11
    assert parsed["team_totals"]["home"]["field_goals_made"] == 31
    assert parsed["team_totals"]["away"]["rebounds"] == 48


# --- 2. REID real stats map correctly (pts=12, reb=6, assist=1, val=14)
def test_reid_maps_to_player_stats():
    parsed = _parsed()
    reid = next(p for p in parsed["stats"]["home"] if p["id"] == "2813013")
    assert reid["pts"] == 12 and reid["reb"] == 6 and reid["assist"] == 1 and reid["val"] == 14


# --- 3. multiple players persisted
def test_all_players_persisted(db, match_repo, stats_repo, idem_repo):
    match = _match()
    match_repo.save(match)
    parsed = _parsed()
    cmd = _command(parsed)
    handler = _handler(match_repo, stats_repo, idem_repo)
    handler.handle(cmd)
    players = list(stats_repo.list_player_stats(MATCH_ID))
    assert len(players) == 21
    reid = next(p for p in players if p.player_external_id == "2813013")
    assert reid.points == 12 and reid.rebounds == 6 and reid.assists == 1


# --- 4. multiple teams persisted
def test_team_stats_persisted(db, match_repo, stats_repo, idem_repo):
    match = _match()
    match_repo.save(match)
    handler = _handler(match_repo, stats_repo, idem_repo)
    handler.handle(_command(_parsed()))
    teams = {ts.team_external_id: ts for ts in stats_repo.list_team_stats(MATCH_ID)}
    assert set(teams) == {"979897", "981281"}
    assert teams["979897"].points_for == 80 and teams["979897"].points_against == 88
    assert teams["981281"].points_for == 88 and teams["981281"].points_against == 80


# --- 5. match without player stats still persists (empty array)
def test_match_without_player_stats(db, match_repo, stats_repo, idem_repo):
    match = _match()
    match_repo.save(match)
    parsed = _parsed()
    parsed["stats"] = {"home": [], "away": []}
    handler = _handler(match_repo, stats_repo, idem_repo)
    handler.handle(_command(parsed))
    assert list(stats_repo.list_player_stats(MATCH_ID)) == []
    assert len(list(stats_repo.list_team_stats(MATCH_ID))) == 2


# --- 6. optional FEB field absent -> defaults zero
def test_optional_feb_field_defaults_zero(db, match_repo, stats_repo, idem_repo):
    match = _match()
    match_repo.save(match)
    parsed = _parsed()
    parsed["stats"]["home"] = [parsed["stats"]["home"][0]]
    parsed["stats"]["away"] = []
    # strip st/bs/to from the only player to prove defaulting
    p = parsed["stats"]["home"][0]
    for k in ("st", "bs", "to"):
        p.pop(k, None)
    handler = _handler(match_repo, stats_repo, idem_repo)
    handler.handle(_command(parsed))
    players = list(stats_repo.list_player_stats(MATCH_ID))
    assert len(players) == 1
    assert players[0].steals == 0 and players[0].blocks == 0 and players[0].turnovers == 0


# --- 7. persistence idempotency (match_external_id + player_external_id UNIQUE)
def test_reingest_does_not_duplicate(db, match_repo, stats_repo, idem_repo):
    match = _match()
    match_repo.save(match)
    handler = _handler(match_repo, stats_repo, idem_repo)
    handler.handle(_command(_parsed()))
    handler.handle(_command(_parsed(), command_id="22222222-2222-2222-2222-222222222222"))
    assert len(list(stats_repo.list_player_stats(MATCH_ID))) == 21
    assert len(list(stats_repo.list_team_stats(MATCH_ID))) == 2


# --- 7b. handler command_id idempotency
def test_same_command_id_returns_no_events(db, match_repo, stats_repo, idem_repo):
    match = _match()
    match_repo.save(match)
    handler = _handler(match_repo, stats_repo, idem_repo)
    cmd = _command(_parsed())
    first = handler.handle(cmd)
    second = handler.handle(cmd)
    assert first  # events recorded on first run
    assert second == []  # idempotent replay: no new events


# --- 8. full fixture reingest end-to-end: parse -> command -> handler -> aggregate
def test_fixture_reingest_matches_aggregate_and_projection(db, match_repo, stats_repo, idem_repo):
    match = _match()
    match_repo.save(match)
    handler = _handler(match_repo, stats_repo, idem_repo)

    cmd1 = _command(_parsed(), command_id="33333333-3333-3333-3333-333333333333")
    handler.handle(cmd1)
    match_after = match_repo.get_by_external_id(ExternalId(MATCH_ID))
    assert match_after is not None
    assert len(match_after.player_stats) == 21
    assert match_after.home_team_stats.points_for == 80
    assert match_after.away_team_stats.points_for == 88
    assert len(list(stats_repo.list_player_stats(MATCH_ID))) == 21
    # raw stays contract-compliant: stats never enter create_or_update_match raw
    cmd_match = M.to_command(_parsed(), "segunda-feb")
    assert set(cmd_match["payload"]["raw"].keys()) == {"boxscore_ref", "teamstats_ref"}


# --- 9. season query for one player
def test_player_stats_by_season(db, match_repo, stats_repo, idem_repo):
    match = _match()
    match_repo.save(match)
    handler = _handler(match_repo, stats_repo, idem_repo)
    handler.handle(_command(_parsed()))
    rows = list(stats_repo.list_player_stats_by_season("2813013", SeasonCode(SEASON)))
    assert len(rows) == 1
    assert rows[0].points == 12


# --- 10. domain round-trip of stats via serialization
def test_stats_round_trip_through_serialization(db, match_repo, stats_repo, idem_repo):
    match = _match()
    match_repo.save(match)
    handler = _handler(match_repo, stats_repo, idem_repo)
    handler.handle(_command(_parsed()))
    loaded = match_repo.get_by_external_id(ExternalId(MATCH_ID))
    reid = next(p for p in loaded.player_stats if p.player_external_id == "2813013")
    assert reid.points == 12 and reid.rebounds == 6 and reid.assists == 1


# --- 11. unknown match -> MatchNotFound
def test_stats_for_unknown_match_raises(db, match_repo, stats_repo, idem_repo):
    from feb_score.domain.errors import MatchNotFound
    handler = _handler(match_repo, stats_repo, idem_repo)
    with pytest.raises(MatchNotFound):
        handler.handle(_command(_parsed()))


# --- 12. full HTTP chain: create match -> upsert stats -> idempotent replay
def test_http_upsert_stats_end_to_end_and_idempotent(pg_client, pg_db):
    from feb_score.infrastructure.persistence.postgres.repositories import PgMatchStatsRepository

    auth = {"Authorization": "Bearer system-key"}
    match_payload = {
        "external_id": MATCH_ID,
        "competition_id": "segunda-feb",
        "season_code": SEASON,
        "round_number": 1,
        "scheduled_at": "2025-10-18T19:00:00+01:00",
        "home_team": {"external_id": "979897", "name": "BUENO ARENAS ALBACETE BASKET"},
        "away_team": {"external_id": "981281", "name": "LOBE HUESCA LA MAGIA"},
        "venue": {"name": "", "city": ""},
        "source": {"id": "feb-intrafeb", "fetched_at": "2026-02-01T20:00:00Z", "s3_path": "s3://feb-live/x"},
        "raw": {"boxscore_ref": "s3://feb-live/x", "teamstats_ref": "s3://feb-live/x"},
    }
    assert pg_client.post("/v1/commands/create_or_update_match", json={"payload": match_payload},
                          headers=auth).status_code == 200

    stats_cmd = M.to_stats_command(_parsed(), "segunda-feb")
    body = {"command_id": stats_cmd["command_id"], "payload": stats_cmd["payload"]}
    resp = pg_client.post("/v1/commands/upsert_match_stats", json=body, headers=auth)
    assert resp.status_code == 200, resp.text
    assert any(e["event_type"] == "match_upserted" for e in resp.json()["events"])

    # replay the SAME command -> no new events (command_id idempotency)
    resp2 = pg_client.post("/v1/commands/upsert_match_stats", json=body, headers=auth)
    assert resp2.status_code == 200, resp2.text
    assert resp2.json()["events"] == []

    repo = PgMatchStatsRepository(pg_db)
    players = list(repo.list_player_stats(MATCH_ID))
    assert len(players) == 21
    reid = next(p for p in players if p.player_external_id == "2813013")
    assert reid.points == 12 and reid.rebounds == 6 and reid.assists == 1


# --- 13. authz: upsert_match_stats requires auth (anon 401); system allowed
def test_http_upsert_stats_authz(pg_client):
    stats_cmd = M.to_stats_command(_parsed(), "segunda-feb")
    body = {"command_id": stats_cmd["command_id"], "payload": stats_cmd["payload"]}
    anon = pg_client.post("/v1/commands/upsert_match_stats", json=body)
    assert anon.status_code == 401
    system = pg_client.post(
        "/v1/commands/upsert_match_stats",
        json=body,
        headers={"Authorization": "Bearer system-key"},
    )
    assert system.status_code in (200, 404)  # match missing here -> 404, but NOT 401/403