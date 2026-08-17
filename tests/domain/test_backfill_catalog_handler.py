"""FASE 25 — BackfillCatalogHandler unit tests (InMemory repositories).

The handler wires CatalogBackfillService to the repositories and uses the
official name resolvers. Resolvers are injected here as deterministic maps so
the tests exercise the handler wiring end-to-end without the FEB network or the
scripts/ sibling modules.
"""

from __future__ import annotations

import uuid

from feb_score.application.commands.commands import BackfillCatalogCommand
from feb_score.application.repositories.in_memory import (
    InMemoryMatchRepository,
    InMemoryMatchStatsRepository,
    InMemoryPlayerRepository,
    InMemoryTeamRepository,
)
from feb_score.application.use_cases.handlers import BackfillCatalogHandler
from feb_score.domain.match.model import Match
from feb_score.domain.player.model import Player
from feb_score.domain.statistics.model import PlayerStats, TeamStats
from feb_score.domain.team.model import Team
from feb_score.domain.value_objects import (
    Actor,
    CommandMeta,
    CompetitionId,
    ExternalId,
    MatchId,
    PlayerId,
    SeasonCode,
    TeamId,
)

SEASON = SeasonCode("2025-2026")
COMP = CompetitionId("segunda-feb")


class _MapResolver:
    def __init__(self, mapping):
        self._mapping = mapping

    def resolve(self, season_code):
        return dict(self._mapping)


def _ps(pid, team):
    return PlayerStats(player_external_id=pid, team_external_id=team, points=1,
                       rebounds=0, assists=0, steals=0, blocks=0, turnovers=0, minutes=1.0)


def _ts(tid):
    return TeamStats(team_external_id=tid, points_for=50, points_against=40,
                     field_goals_made=1, field_goals_attempted=2, three_points_made=0,
                     three_points_attempted=1, free_throws_made=0, free_throws_attempted=0,
                     turnovers=0, rebounds=0)


def _match(ext):
    m = Match(match_id=MatchId(str(uuid.uuid4())), external_id=ExternalId(ext),
              competition_id=COMP, season_code=SEASON, status="FINALIZED",
              round_number=1, home_team_id=ExternalId("T1"),
              away_team_id=ExternalId("T2"), scheduled_at="2025-10-04T00:00:00+01:00")
    return m


def _command(payload):
    return BackfillCatalogCommand(
        command_id=str(uuid.uuid4()),
        meta=CommandMeta(version="1.0", issued_at="2026-01-01T00:00:00Z"),
        actor=Actor(id="admin-1", role="admin"),
        payload=payload,
    )


def _build(**kwargs):
    stats = InMemoryMatchStatsRepository()
    stats.save_player_stats("M1", SEASON, [_ps("P1", "T1"), _ps("P2", "T1"), _ps("P3", "T2")])
    stats.save_team_stats("M1", SEASON, [_ts("T1"), _ts("T2")])
    matches = InMemoryMatchRepository()
    m = _match("M1")
    m.record_stats(home_team_stats=_ts("T1"), away_team_stats=_ts("T2"),
                   player_stats=(_ps("P1", "T1"),), actor_id="admin-1")
    matches.save(m)
    players = kwargs.get("players") or InMemoryPlayerRepository()
    teams = kwargs.get("teams") or InMemoryTeamRepository()
    handler = BackfillCatalogHandler(
        matches, stats, players, teams,
        player_names=kwargs.get("player_names") or _MapResolver({}),
        team_names=kwargs.get("team_names") or _MapResolver({}),
    )
    return handler, matches, stats, players, teams


def test_backfill_catalog_players_with_official_names():
    handler, _, _, players, _ = _build(
        player_names=_MapResolver({"P1": "JUAN", "P2": "MARIA", "P3": "LUCIA"}),
    )
    events = handler.handle(_command({"season_code": "2025-2026", "entity": "players"}))
    assert events == []
    p = players.get_by_external_id(ExternalId("P1"))
    assert p is not None and p.name == "JUAN"


def test_backfill_catalog_both_entities():
    handler, _, _, players, teams = _build(
        player_names=_MapResolver({"P1": "JUAN", "P2": "MARIA", "P3": "LUCIA"}),
        team_names=_MapResolver({"T1": "CLUB UNO", "T2": "CLUB DOS"}),
    )
    events = handler.handle(_command({"season_code": "2025-2026", "entity": "both"}))
    assert events == []
    assert players.get_by_external_id(ExternalId("P2")).name == "MARIA"
    assert teams.get_by_external_id(ExternalId("T1")).name == "CLUB UNO"


def test_backfill_catalog_dry_run_writes_nothing():
    handler, _, _, players, _ = _build(
        player_names=_MapResolver({"P1": "JUAN", "P2": "MARIA", "P3": "LUCIA"}),
    )
    events = handler.handle(_command(
        {"season_code": "2025-2026", "entity": "players", "dry_run": True}
    ))
    assert events == []
    assert players.get_by_external_id(ExternalId("P1")) is None


def test_backfill_catalog_idempotent_replay():
    handler, _, _, players, _ = _build(
        player_names=_MapResolver({"P1": "JUAN", "P2": "MARIA", "P3": "LUCIA"}),
    )
    cmd = _command({"season_code": "2025-2026", "entity": "players"})
    handler.handle(cmd)
    p_before = players.get_by_external_id(ExternalId("P1"))
    handler.handle(cmd)
    p_after = players.get_by_external_id(ExternalId("P1"))
    assert p_after.name == p_before.name