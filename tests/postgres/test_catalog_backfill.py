"""FASE 24.1 — Catalog backfill cross-backend contract tests (SQLite + PostgreSQL).

Covers the conservative ``upsert_catalog`` write path and the
``CatalogBackfillService`` behavior on both backends: create / no-duplicate /
NULL-fill / preserve-on-conflict, single catalog identity across matches,
season isolation, replay idempotency, and the invariant that stats and matches
are untouched.
"""

from __future__ import annotations

import json
from uuid import uuid4

from feb_score.application.use_cases.catalog_backfill_service import (
    CatalogBackfillService,
)
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


def _match(external_id, home, away, season=SEASON):
    return Match(
        external_id=ExternalId(external_id),
        match_id=MatchId(str(uuid4())),
        competition_id=CompetitionId("segunda-feb"),
        season_code=season,
        round_number=1,
        home_team_id=ExternalId(home),
        away_team_id=ExternalId(away),
        scheduled_at=None,
    )


def _ps(pid, team, pts=1):
    return PlayerStats(player_external_id=pid, team_external_id=team, points=pts,
                       rebounds=0, assists=0, steals=0, blocks=0, turnovers=0, minutes=1.0)


def _ts(tid, pf=50, pa=40):
    return TeamStats(team_external_id=tid, points_for=pf, points_against=pa,
                     field_goals_made=1, field_goals_attempted=2, three_points_made=0,
                     three_points_attempted=1, free_throws_made=0, free_throws_attempted=0,
                     turnovers=0, rebounds=0)


class _MapResolver:
    def __init__(self, mapping):
        self._mapping = mapping

    def resolve(self, season_code):
        return dict(self._mapping)


def _seed(backend):
    db = backend.make_db()
    match_repo = backend.repo(db, "match")
    stats_repo = backend.repo(db, "stats")
    player_repo = backend.repo(db, "player")
    team_repo = backend.repo(db, "team")
    match_repo.save(_match("M1", "T1", "T2"))
    match_repo.save(_match("M2", "T1", "T3"))
    stats_repo.save_player_stats("M1", SEASON, [_ps("P1", "T1"), _ps("P2", "T2"), _ps("P3", "T2")])
    stats_repo.save_player_stats("M2", SEASON, [_ps("P1", "T1"), _ps("P4", "T3")])
    stats_repo.save_team_stats("M1", SEASON, [_ts("T1"), _ts("T2")])
    stats_repo.save_team_stats("M2", SEASON, [_ts("T1", 60, 30), _ts("T3")])
    svc = CatalogBackfillService(
        player_repo, team_repo, stats_repo,
        player_names=_MapResolver({"P1": "JUAN", "P2": "MARIA"}),
        team_names=_MapResolver({"T1": "CLUB UNO"}),
    )
    return db, svc, stats_repo, player_repo, team_repo


# ===========================================================================
# Players (1-7)
# ===========================================================================


def test_player_create_unknown_and_duplicate_check(backend):
    db, svc, _, player_repo, _ = _seed(backend)
    first = svc.run(SEASON, entities=("players",))
    assert first.created == 4 and first.errors == 0
    p1 = player_repo.get_by_external_id(ExternalId("P1"))
    assert p1.name == "JUAN"
    p3 = player_repo.get_by_external_id(ExternalId("P3"))
    assert p3.name is None  # NULL when no official name

    second = svc.run(SEASON, entities=("players",))
    assert (second.created, second.updated, second.skipped, second.errors) == (0, 0, 4, 0)


def test_player_fill_null_name_and_preserve_identity(backend):
    db, svc, stats_repo, player_repo, _ = _seed(backend)
    svc.run(SEASON, entities=("players",))
    p1 = player_repo.get_by_external_id(ExternalId("P1"))
    first_id = p1.player_id
    svc2 = CatalogBackfillService(
        player_repo, backend.repo(db, "team"), stats_repo,
        player_names=_MapResolver({"P3": "CARLOS"}),
    )
    result = svc2.run(SEASON, entities=("players",))
    assert result.updated == 1
    p3 = player_repo.get_by_external_id(ExternalId("P3"))
    assert p3.name == "CARLOS"
    # identity is canonical on external_id; player_id preserved on later runs
    assert player_repo.get_by_external_id(ExternalId("P1")).player_id == first_id
    svc.run(SEASON, entities=("players",))
    assert player_repo.get_by_external_id(ExternalId("P1")).player_id == first_id


def test_player_conflict_preserves_existing_name(backend):
    db, svc, _, player_repo, _ = _seed(backend)
    player_repo.save(Player(external_id=ExternalId("P1"), player_id=PlayerId(str(uuid4())),
                            name="NOMBRE EXISTENTE"))
    result = svc.run(SEASON, entities=("players",))
    assert player_repo.get_by_external_id(ExternalId("P1")).name == "NOMBRE EXISTENTE"
    assert any("keeping existing name" in w for w in result.warnings)


def test_player_single_catalog_across_matches(backend):
    db, svc, _, player_repo, _ = _seed(backend)
    svc.run(SEASON, entities=("players",))
    hits = list(player_repo.search_by_name("JUAN"))
    assert len(hits) == 1 and str(hits[0].external_id) == "P1"


def test_player_season_isolation(backend):
    db = backend.make_db()
    stats_repo = backend.repo(db, "stats")
    player_repo = backend.repo(db, "player")
    stats_repo.save_player_stats("M1", SEASON, [_ps("P1", "T1")])
    stats_repo.save_player_stats("MX", SeasonCode("2024-2025"), [_ps("PX", "T9")])
    svc = CatalogBackfillService(
        player_repo, backend.repo(db, "team"), stats_repo,
        player_names=_MapResolver({"P1": "JUAN"}),
    )
    svc.run(SEASON, entities=("players",))
    assert player_repo.get_by_external_id(ExternalId("PX")) is None
    assert player_repo.get_by_external_id(ExternalId("P1")) is not None


# ===========================================================================
# Teams (8-12)
# ===========================================================================


def test_team_create_unknown_and_duplicate_check(backend):
    db, svc, _, _, team_repo = _seed(backend)
    first = svc.run(SEASON, entities=("teams",))
    assert first.created == 3 and first.errors == 0
    assert team_repo.get_by_external_id(ExternalId("T1")).name == "CLUB UNO"
    assert team_repo.get_by_external_id(ExternalId("T2")).name is None
    second = svc.run(SEASON, entities=("teams",))
    assert (second.created, second.updated, second.skipped, second.errors) == (0, 0, 3, 0)


def test_team_fill_null_name(backend):
    db, svc, _, _, team_repo = _seed(backend)
    svc.run(SEASON, entities=("teams",))
    assert team_repo.get_by_external_id(ExternalId("T2")).name is None
    svc2 = CatalogBackfillService(
        backend.repo(db, "player"), team_repo, backend.repo(db, "stats"),
        team_names=_MapResolver({"T2": "CLUB DOS"}),
    )
    result = svc2.run(SEASON, entities=("teams",))
    assert result.updated == 1
    assert team_repo.get_by_external_id(ExternalId("T2")).name == "CLUB DOS"


def test_team_conflict_preserves_existing_name(backend):
    db, svc, _, _, team_repo = _seed(backend)
    team_repo.save(Team(external_id=ExternalId("T1"), team_id=TeamId(str(uuid4())),
                        name="EXISTENTE"))
    result = svc.run(SEASON, entities=("teams",))
    assert team_repo.get_by_external_id(ExternalId("T1")).name == "EXISTENTE"
    assert any("keeping existing name" in w for w in result.warnings)


def test_team_single_catalog_across_matches(backend):
    db, svc, _, _, team_repo = _seed(backend)
    svc.run(SEASON, entities=("teams",))
    hits = list(team_repo.search_by_name("CLUB UNO"))
    assert len(hits) == 1 and str(hits[0].external_id) == "T1"


def test_team_season_isolation(backend):
    db = backend.make_db()
    stats_repo = backend.repo(db, "stats")
    team_repo = backend.repo(db, "team")
    stats_repo.save_team_stats("M1", SEASON, [_ts("T1")])
    stats_repo.save_team_stats("MX", SeasonCode("2024-2025"), [_ts("TX")])
    svc = CatalogBackfillService(
        backend.repo(db, "player"), team_repo, stats_repo,
        team_names=_MapResolver({"T1": "CLUB UNO"}),
    )
    svc.run(SEASON, entities=("teams",))
    assert team_repo.get_by_external_id(ExternalId("TX")) is None


# ===========================================================================
# Replay (13-15)
# ===========================================================================


def test_replay_idempotent_and_preserves_stats_matches(backend):
    db, svc, stats_repo, player_repo, team_repo = _seed(backend)
    players_before = list(stats_repo.list_player_stats("M1"))
    teams_before = list(stats_repo.list_team_stats("M1"))
    svc.run(SEASON)
    svc.run(SEASON)
    assert list(stats_repo.list_player_stats("M1")) == players_before
    assert list(stats_repo.list_team_stats("M1")) == teams_before
    # single catalog identity per external_id (UNIQUE constraint + no dup rows)
    assert player_repo.get_by_external_id(ExternalId("P1")) is not None
    assert team_repo.get_by_external_id(ExternalId("T1")) is not None
    assert len(list(player_repo.search_by_name("JUAN"))) == 1


def test_replay_preserves_entity_ids(backend):
    db, svc, _, player_repo, team_repo = _seed(backend)
    svc.run(SEASON)
    pid = str(player_repo.get_by_external_id(ExternalId("P1")).player_id)
    tid = str(team_repo.get_by_external_id(ExternalId("T1")).team_id)
    svc.run(SEASON)
    assert str(player_repo.get_by_external_id(ExternalId("P1")).player_id) == pid
    assert str(team_repo.get_by_external_id(ExternalId("T1")).team_id) == tid


def test_upsert_catalog_preserves_existing_id_and_null_fills(backend):
    db = backend.make_db()
    repo = backend.repo(db, "player")
    first_id = str(uuid4())
    repo.upsert_catalog(ExternalId("P1"), PlayerId(first_id), "JUAN", json.dumps(
        {"external_id": "P1", "player_id": first_id, "name": "JUAN"}))
    repo.upsert_catalog(ExternalId("P1"), PlayerId(str(uuid4())), "NUEVO", json.dumps(
        {"external_id": "P1", "player_id": str(uuid4()), "name": "NUEVO"}))
    p = repo.get_by_external_id(ExternalId("P1"))
    assert str(p.player_id) == first_id  # existing id preserved
    assert p.name == "JUAN"  # existing valid name preserved
    # NULL name gets filled
    repo.upsert_catalog(ExternalId("P2"), PlayerId(str(uuid4())), None, json.dumps(
        {"external_id": "P2", "player_id": str(uuid4()), "name": None}))
    repo.upsert_catalog(ExternalId("P2"), PlayerId(str(uuid4())), "MARIA", json.dumps(
        {"external_id": "P2", "player_id": str(uuid4()), "name": "MARIA"}))
    p2 = repo.get_by_external_id(ExternalId("P2"))
    assert p2.name == "MARIA"