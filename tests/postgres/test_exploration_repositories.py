"""FASE 24 — Exploration repository contract tests (cross-backend).

The SAME test bodies run against BOTH backends (parametrized ``backend``
fixture): SQLite and PostgreSQL. Passing here means both implementations respect
the same public semantics for:

* ``MatchRepository.search``         — FASE 24.4 deterministic match search;
* ``PlayerRepository.search_by_name``/``TeamRepository.search_by_name`` — FASE
  24.4 literal, case-insensitive name search;
* ``MatchStatsRepository.list_season_team_rounds`` — FASE 24.3 per-round
  evolution joined with the owning match's stored round_number.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest

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

SEASON = "2025-2026"


def _match(external_id, round_number, home, away, competition="feb-comp", season=SEASON):
    return Match(
        external_id=ExternalId(external_id),
        match_id=MatchId(str(uuid4())),
        competition_id=CompetitionId(competition),
        season_code=SeasonCode(season),
        round_number=round_number,
        home_team_id=ExternalId(home),
        away_team_id=ExternalId(away),
        scheduled_at=datetime(2026, 2, 1, 18, 30),
    )


def _ps(pid, team):
    return PlayerStats(
        player_external_id=pid, team_external_id=team, points=1,
        rebounds=0, assists=0, steals=0, blocks=0, turnovers=0, minutes=1.0,
    )


def _ts(tid, pf, pa):
    return TeamStats(
        team_external_id=tid, points_for=pf, points_against=pa,
        field_goals_made=10, field_goals_attempted=20, three_points_made=3,
        three_points_attempted=8, free_throws_made=4, free_throws_attempted=6,
        turnovers=5, rebounds=20,
    )


# ===========================================================================
# MatchRepository.search (24.4)
# ===========================================================================

def _seed_matches(backend):
    db = backend.make_db()
    repo = backend.repo(db, "match")
    repo.save(_match("M-003", 1, "T1", "T2"))
    repo.save(_match("M-001", 1, "T3", "T4"))
    repo.save(_match("M-002", 2, "T1", "T5"))
    repo.save(_match("M-101", 1, "T1", "T6", competition="other-comp"))
    repo.save(_match("M-009", 1, "T1", "T7", season="2024-2025"))
    return db, repo


def test_match_search_season_scoped_deterministic(backend):
    db, repo = _seed_matches(backend)
    ids = lambda kw: [str(m.external_id) for m in repo.search(SeasonCode(SEASON), **kw)]

    assert ids({}) == ["M-001", "M-002", "M-003", "M-101"]  # ASC by external_id
    assert ids({"competition_id": CompetitionId("feb-comp")}) == ["M-001", "M-002", "M-003"]
    assert ids({"round_number": 1}) == ["M-001", "M-003", "M-101"]
    assert ids({"round_number": 2}) == ["M-002"]
    assert ids({"team_external_id": "T1"}) == ["M-002", "M-003", "M-101"]  # home OR away
    assert ids({"external_id_query": "M-00"}) == ["M-001", "M-002", "M-003"]
    assert ids({"external_id_query": "M-00", "limit": 2}) == ["M-001", "M-002"]
    assert ids({"external_id_query": "m-1"}) == ["M-101"]  # case-insensitive


def test_match_search_rejects_invalid_round(backend):
    db, repo = _seed_matches(backend)
    with pytest.raises(ValueError):
        repo.search(SeasonCode(SEASON), round_number=0)
    with pytest.raises(ValueError):
        repo.search(SeasonCode(SEASON), round_number=-1)


def test_match_search_returns_full_aggregates(backend):
    db, repo = _seed_matches(backend)
    matches = list(repo.search(SeasonCode(SEASON), external_id_query="M-001"))
    assert len(matches) == 1
    assert matches[0].round_number == 1
    assert str(matches[0].home_team_id) == "T3"


# ===========================================================================
# Player/Team search_by_name (24.4)
# ===========================================================================

def test_player_search_by_name(backend):
    db = backend.make_db()
    repo = backend.repo(db, "player")
    repo.save(Player(external_id=ExternalId("p-2"), player_id=PlayerId(str(uuid4())), name="Marc Lopez"))
    repo.save(Player(external_id=ExternalId("p-1"), player_id=PlayerId(str(uuid4())), name="Juan Garcia"))
    repo.save(Player(external_id=ExternalId("p-3"), player_id=PlayerId(str(uuid4())), name="Marcos Lopez"))

    ids = lambda q, **kw: [str(p.external_id) for p in repo.search_by_name(q, **kw)]
    assert ids("lopez") == ["p-2", "p-3"]  # case-insensitive substring
    assert ids("MARC") == ["p-2", "p-3"]
    assert ids("garcia") == ["p-1"]
    assert ids("zzz") == []
    assert ids("lopez", limit=1) == ["p-2"]
    # wildcards are literal, never interpreted
    assert ids("%") == []
    assert ids("_") == []


def test_player_season_teams_derived_from_stats(backend):
    """FASE 24.2 — distinct teams a player appeared for in a season."""
    db = backend.make_db()
    match_repo = backend.repo(db, "match")
    stats_repo = backend.repo(db, "stats")
    match_repo.save(_match("M-1", 1, "T1", "T2"))
    match_repo.save(_match("M-2", 1, "T1", "T3"))
    match_repo.save(_match("M-3", 2, "T3", "T2"))
    match_repo.save(_match("M-9", 1, "T1", "T2", season="2024-2025"))
    stats_repo.save_player_stats("M-1", SeasonCode(SEASON), [
        _ps("P1", "T1"), _ps("P2", "T2")])
    stats_repo.save_player_stats("M-2", SeasonCode(SEASON), [
        _ps("P1", "T1"), _ps("P3", "T3")])
    stats_repo.save_player_stats("M-3", SeasonCode(SEASON), [
        _ps("P1", "T3"), _ps("P2", "T2")])
    stats_repo.save_player_stats("M-9", SeasonCode("2024-2025"), [_ps("P1", "T1")])

    assert list(stats_repo.list_player_season_teams("P1", SeasonCode(SEASON))) == ["T1", "T3"]
    assert list(stats_repo.list_player_season_teams("P2", SeasonCode(SEASON))) == ["T2"]
    assert list(stats_repo.list_player_season_teams("P3", SeasonCode(SEASON))) == ["T3"]
    # season isolation + no data
    assert list(stats_repo.list_player_season_teams("P1", SeasonCode("2024-2025"))) == ["T1"]
    assert list(stats_repo.list_player_season_teams("P9", SeasonCode(SEASON))) == []


def test_team_search_by_name(backend):
    db = backend.make_db()
    repo = backend.repo(db, "team")
    repo.save(Team(external_id=ExternalId("t-2"), team_id=TeamId(str(uuid4())), name="Club Dos"))
    repo.save(Team(external_id=ExternalId("t-1"), team_id=TeamId(str(uuid4())), name="Club Uno"))

    ids = lambda q, **kw: [str(t.external_id) for t in repo.search_by_name(q, **kw)]
    assert ids("club") == ["t-1", "t-2"]
    assert ids("DOS") == ["t-2"]
    assert ids("uno") == ["t-1"]
    assert ids("%") == []


# ===========================================================================
# MatchStatsRepository.list_season_team_rounds (24.3)
# ===========================================================================

def _seed_team_rounds(backend):
    db = backend.make_db()
    match_repo = backend.repo(db, "match")
    stats_repo = backend.repo(db, "stats")
    # T1: round 1 wins over T2 and T5, round 2 loss to T6
    match_repo.save(_match("M-1", 1, "T1", "T2"))
    match_repo.save(_match("M-2", 1, "T1", "T5"))
    match_repo.save(_match("M-3", 2, "T1", "T6"))
    # same match ids in another season must not contaminate
    match_repo.save(_match("M-9", 1, "T1", "T2", season="2024-2025"))

    stats_repo.save_team_stats("M-1", SeasonCode(SEASON), [_ts("T1", 80, 70), _ts("T2", 70, 80)])
    stats_repo.save_team_stats("M-2", SeasonCode(SEASON), [_ts("T1", 90, 85), _ts("T5", 85, 90)])
    stats_repo.save_team_stats("M-3", SeasonCode(SEASON), [_ts("T1", 60, 65), _ts("T6", 65, 60)])
    stats_repo.save_team_stats("M-9", SeasonCode("2024-2025"), [_ts("T1", 100, 50)])
    return db, stats_repo


def test_team_rounds_evolution(backend):
    db, repo = _seed_team_rounds(backend)
    rounds = list(repo.list_season_team_rounds("T1", SeasonCode(SEASON)))
    assert [(r.round_number, r.games_played, r.wins, r.losses,
             r.points_for, r.points_against, r.point_difference) for r in rounds] == [
        (1, 2, 2, 0, 170, 155, 15),
        (2, 1, 0, 1, 60, 65, -5),
    ]


def test_team_rounds_ignores_other_seasons_and_teams(backend):
    db, repo = _seed_team_rounds(backend)
    to_tuple = lambda rs: [(r.round_number, r.games_played, r.wins, r.losses,
                            r.points_for, r.points_against, r.point_difference) for r in rs]
    assert to_tuple(repo.list_season_team_rounds("T1", SeasonCode("2024-2025"))) == [(1, 1, 1, 0, 100, 50, 50)]
    assert to_tuple(repo.list_season_team_rounds("T2", SeasonCode(SEASON))) == [(1, 1, 0, 1, 70, 80, -10)]
    assert list(repo.list_season_team_rounds("T9", SeasonCode(SEASON))) == []


def test_team_rounds_matches_without_round_are_excluded(backend):
    """A stats row whose owning match has no stored round_number must not produce
    a null-round bucket (the round belongs to the match data, not the stats)."""
    db = backend.make_db()
    match_repo = backend.repo(db, "match")
    stats_repo = backend.repo(db, "stats")
    match = _match("M-X", 1, "T1", "T2")
    match_repo.save(match)
    # drop the round_number from the stored blob to simulate a degraded record
    from feb_score.application.persistence import serialization as S

    conn, owned = db.connect(), True
    try:
        data = S.match_to_dict(match)
        del data["round_number"]
        import json
        conn.execute(
            "UPDATE matches SET data = %s::jsonb WHERE external_id = %s"
            if backend.name == "postgres"
            else "UPDATE matches SET data = ? WHERE external_id = ?",
            (json.dumps(data), "M-X"),
        )
    finally:
        if owned:
            conn.close()

    stats_repo.save_team_stats("M-X", SeasonCode(SEASON), [_ts("T1", 50, 40)])
    assert list(stats_repo.list_season_team_rounds("T1", SeasonCode(SEASON))) == []