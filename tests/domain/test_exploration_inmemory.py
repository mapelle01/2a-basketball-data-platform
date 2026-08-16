"""FASE 24 — InMemory repository + ExplorationService unit tests.

Covers the InMemory implementations of the FASE 24 repository contract (match
search, player/team name search, per-round team evolution) and the
``ExplorationService`` composition rules (match detail boxscore ordering,
profile None-totals policy, deterministic ordering). No SQL, no HTTP.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest

from feb_score.application.repositories.in_memory import (
    InMemoryMatchRepository,
    InMemoryMatchStatsRepository,
    InMemoryPlayerRepository,
    InMemoryTeamRepository,
)
from feb_score.application.use_cases.exploration_service import ExplorationService
from feb_score.domain.match.model import Match
from feb_score.domain.player.model import Player
from feb_score.domain.statistics.model import PlayerStats, TeamStats
from feb_score.domain.team.model import Team
from feb_score.domain.value_objects import (
    CompetitionId,
    ExternalId,
    MatchId,
    PlayerId,
    SeasonCode,
    TeamId,
)

SEASON = SeasonCode("2025-2026")


def _match(external_id, round_number, home, away, competition="feb-comp", season=SEASON):
    return Match(
        external_id=ExternalId(external_id),
        match_id=MatchId(str(uuid4())),
        competition_id=CompetitionId(competition),
        season_code=season,
        round_number=round_number,
        home_team_id=ExternalId(home),
        away_team_id=ExternalId(away),
        scheduled_at=datetime(2026, 2, 1, 18, 30),
    )


def _ts(tid, pf, pa):
    return TeamStats(
        team_external_id=tid, points_for=pf, points_against=pa,
        field_goals_made=10, field_goals_attempted=20, three_points_made=3,
        three_points_attempted=8, free_throws_made=4, free_throws_attempted=6,
        turnovers=5, rebounds=20,
    )


def _ps(pid, team, pts):
    return PlayerStats(player_external_id=pid, team_external_id=team, points=pts,
                       rebounds=1, assists=1, steals=0, blocks=0, turnovers=0, minutes=10.0)


def _build_service():
    return ExplorationService(
        InMemoryMatchRepository(),
        InMemoryPlayerRepository(),
        InMemoryTeamRepository(),
        InMemoryMatchStatsRepository(),
    )


# ===========================================================================
# InMemory repositories
# ===========================================================================

def test_inmemory_match_search():
    repo = InMemoryMatchRepository()
    for ext, rnd, comp, season in (
        ("M-003", 1, "feb-comp", SEASON),
        ("M-001", 1, "feb-comp", SEASON),
        ("M-002", 2, "feb-comp", SEASON),
        ("M-101", 1, "other-comp", SEASON),
        ("M-009", 1, "feb-comp", SeasonCode("2024-2025")),
    ):
        repo.save(_match(ext, rnd, "T1", "T2", competition=comp, season=season))

    ids = lambda kw: [str(m.external_id) for m in repo.search(SEASON, **kw)]
    assert ids({}) == ["M-001", "M-002", "M-003", "M-101"]
    assert ids({"competition_id": CompetitionId("feb-comp")}) == ["M-001", "M-002", "M-003"]
    assert ids({"round_number": 1}) == ["M-001", "M-003", "M-101"]
    assert ids({"team_external_id": "T1"}) == ["M-001", "M-002", "M-003", "M-101"]
    assert ids({"external_id_query": "M-00"}) == ["M-001", "M-002", "M-003"]
    assert ids({"external_id_query": "m-1"}) == ["M-101"]
    assert ids({"external_id_query": "M-00", "limit": 2}) == ["M-001", "M-002"]

    with pytest.raises(ValueError):
        repo.search(SEASON, round_number=0)


def test_inmemory_name_search():
    players = InMemoryPlayerRepository()
    players.save(Player(external_id=ExternalId("p-2"), player_id=PlayerId(str(uuid4())), name="Marc Lopez"))
    players.save(Player(external_id=ExternalId("p-1"), player_id=PlayerId(str(uuid4())), name="Juan Garcia"))
    assert [str(p.external_id) for p in players.search_by_name("lopez")] == ["p-2"]
    assert [str(p.external_id) for p in players.search_by_name("MARC")] == ["p-2"]
    assert [str(p.external_id) for p in players.search_by_name("%")] == []
    assert [str(p.external_id) for p in players.search_by_name("garcia", limit=0)] == []

    teams = InMemoryTeamRepository()
    teams.save(Team(external_id=ExternalId("t-2"), team_id=TeamId(str(uuid4())), name="Club Dos"))
    teams.save(Team(external_id=ExternalId("t-1"), team_id=TeamId(str(uuid4())), name="Club Uno"))
    assert [str(t.external_id) for t in teams.search_by_name("club")] == ["t-1", "t-2"]


def test_inmemory_team_rounds():
    stats = InMemoryMatchStatsRepository()
    stats.save_team_stats("M-1", SEASON, [_ts("T1", 80, 70), _ts("T2", 70, 80)], round_number=1)
    stats.save_team_stats("M-2", SEASON, [_ts("T1", 90, 85)], round_number=1)
    stats.save_team_stats("M-3", SEASON, [_ts("T1", 60, 65)], round_number=2)
    # no round recorded -> excluded (mirrors SQL backends)
    stats.save_team_stats("M-4", SEASON, [_ts("T1", 50, 40)])

    rounds = list(stats.list_season_team_rounds("T1", SEASON))
    assert [(r.round_number, r.games_played, r.wins, r.losses,
             r.points_for, r.points_against, r.point_difference) for r in rounds] == [
        (1, 2, 2, 0, 170, 155, 15),
        (2, 1, 0, 1, 60, 65, -5),
    ]


# ===========================================================================
# ExplorationService
# ===========================================================================

def test_service_match_detail_sorted_and_absent():
    service = _build_service()
    assert service.get_match_detail(ExternalId("M-1")) is None

    service._matches.save(_match("M-1", 1, "T1", "T2"))
    service._stats.save_player_stats("M-1", SEASON, [_ps("PB", "T2", 5), _ps("PA", "T1", 22)])
    service._stats.save_team_stats("M-1", SEASON, [_ts("T2", 70, 80), _ts("T1", 80, 70)])

    detail = service.get_match_detail(ExternalId("M-1"))
    assert detail is not None
    assert [t.team_external_id for t in detail.team_stats] == ["T1", "T2"]  # sorted
    assert [p.player_external_id for p in detail.player_stats] == ["PA", "PB"]  # sorted


def test_service_player_profile_policy():
    service = _build_service()
    assert service.get_player_profile(SEASON, "PA") is None

    player = Player(external_id=ExternalId("PA"), player_id=PlayerId(str(uuid4())), name="Ana")
    player.register_for_team("T1", SEASON, dorsal=7)
    service._players.save(player)
    # registered but no stats -> teams present, totals/metrics None (nothing invented)
    profile = service.get_player_profile(SEASON, "PA")
    assert profile is not None
    assert [reg.team_external_id for reg in profile.teams] == ["T1"]
    assert profile.totals is None and profile.metrics is None

    service._stats.save_player_stats("M-1", SEASON, [_ps("PA", "T1", 22)])
    service._stats.save_player_stats("M-2", SEASON, [_ps("PA", "T1", 30)])
    profile = service.get_player_profile(SEASON, "PA")
    assert profile.totals.points == 52
    assert profile.totals.games_played == 2
    assert abs(profile.metrics.points_per_game - 26.0) < 1e-9

    # season filter: another season has no data for PA
    other = service.get_player_profile(SeasonCode("2024-2025"), "PA")
    assert other.totals is None and other.metrics is None and other.teams == ()


def test_service_team_profile_rounds():
    service = _build_service()
    service._teams.save(Team(external_id=ExternalId("T1"), team_id=TeamId(str(uuid4())), name="Club"))
    service._matches.save(_match("M-1", 1, "T1", "T2"))
    service._matches.save(_match("M-2", 2, "T1", "T2"))
    service._stats.save_team_stats("M-1", SEASON, [_ts("T1", 80, 70)], round_number=1)
    service._stats.save_team_stats("M-2", SEASON, [_ts("T1", 60, 65)], round_number=2)

    profile = service.get_team_profile(SEASON, "T1")
    assert profile.totals.wins == 1 and profile.totals.losses == 1
    assert [r.round_number for r in profile.rounds] == [1, 2]

    assert service.get_team_profile(SEASON, "absent") is None


def test_service_player_profile_derived_from_stats():
    service = _build_service()
    service._stats.save_player_stats("M-1", SEASON, [_ps("PX", "T1", 9), _ps("PY", "T1", 5)])
    # PX has stats but no catalog record -> derived identity (player=None)
    profile = service.get_player_profile(SEASON, "PX")
    assert profile is not None
    assert profile.player is None
    assert [reg.team_external_id for reg in profile.teams] == ["T1"]
    assert profile.totals.points == 9
    # PY also stats-only; absent -> no catalog AND no stats
    assert service.get_player_profile(SEASON, "noone") is None


def test_service_team_profile_derived_from_stats():
    service = _build_service()
    service._teams.save(Team(external_id=ExternalId("T1"), team_id=TeamId(str(uuid4())), name="Club"))
    service._matches.save(_match("M-1", 1, "T1", "T2"))
    service._stats.save_team_stats("M-1", SEASON, [_ts("T2", 70, 80)], round_number=1)
    # T2 has stats but no catalog record -> derived identity (team=None)
    profile = service.get_team_profile(SEASON, "T2")
    assert profile is not None
    assert profile.team is None
    assert profile.totals.points_for == 70
    assert [(r.round_number, r.games_played) for r in profile.rounds] == [(1, 1)]
    assert service.get_team_profile(SEASON, "noone") is None


def test_service_search_delegation():
    service = _build_service()
    service._players.save(Player(external_id=ExternalId("p-1"), player_id=PlayerId(str(uuid4())), name="Ana"))
    service._teams.save(Team(external_id=ExternalId("t-1"), team_id=TeamId(str(uuid4())), name="Club"))
    service._matches.save(_match("M-1", 1, "T1", "T2"))

    assert [p.external_id for p in service.search_players("ana")] == [ExternalId("p-1")]
    assert [t.external_id for t in service.search_teams("club")] == [ExternalId("t-1")]
    assert [m.external_id for m in service.search_matches(SEASON)] == [ExternalId("M-1")]