"""FASE 24.1 — CatalogBackfillService unit tests (InMemory repositories).

Covers the canonical-identity and deterministic name-policy rules: entity
enumeration from the season stats projection, create / no-duplicate / NULL-fill
/ preserve / conflict warning, cross-match single catalog identity, replay
idempotency, and the invariant that stats/matches are never touched.
"""

from __future__ import annotations

from uuid import uuid4

from feb_score.application.repositories.in_memory import (
    InMemoryMatchStatsRepository,
    InMemoryPlayerRepository,
    InMemoryTeamRepository,
)
from feb_score.application.use_cases.catalog_backfill_service import (
    CatalogBackfillService,
)
from feb_score.domain.player.model import Player
from feb_score.domain.statistics.model import PlayerStats, TeamStats
from feb_score.domain.team.model import Team
from feb_score.domain.value_objects import ExternalId, PlayerId, SeasonCode, TeamId

SEASON = SeasonCode("2025-2026")


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


def _build(players=None, teams=None):
    stats = InMemoryMatchStatsRepository()
    stats.save_player_stats("M1", SEASON, [_ps("P1", "T1"), _ps("P2", "T1"), _ps("P3", "T2")])
    stats.save_player_stats("M2", SEASON, [_ps("P1", "T1"), _ps("P4", "T3")])
    stats.save_team_stats("M1", SEASON, [_ts("T1"), _ts("T2")])
    stats.save_team_stats("M2", SEASON, [_ts("T1", 60, 30), _ts("T3")])
    p_repo = players or InMemoryPlayerRepository()
    t_repo = teams or InMemoryTeamRepository()
    svc = CatalogBackfillService(
        p_repo, t_repo, stats,
        player_names=_MapResolver({"P1": "JUAN", "P2": "MARIA"}),
        team_names=_MapResolver({"T1": "CLUB UNO"}),
    )
    return svc, stats, p_repo, t_repo


# ===========================================================================
# Players
# ===========================================================================


def test_players_create_unknown_entities():
    svc, _, p_repo, _ = _build()
    result = svc.run(SEASON, entities=("players",))
    assert result.created == 4  # P1..P4 (stats-only identities)
    assert result.errors == 0
    p1 = p_repo.get_by_external_id(ExternalId("P1"))
    assert p1.name == "JUAN"
    p3 = p_repo.get_by_external_id(ExternalId("P3"))
    assert p3.name is None  # no official name -> NULL (documented gap)
    # canonical identity is the external_id, never the name
    assert str(p1.external_id) == "P1"


def test_players_no_duplicate_on_rerun():
    svc, _, _, _ = _build()
    first = svc.run(SEASON, entities=("players",))
    second = svc.run(SEASON, entities=("players",))
    assert first.created == 4
    assert second.created == 0 and second.updated == 0 and second.skipped == 4


def test_players_fill_null_name_when_official_appears():
    svc, stats, p_repo, _ = _build()
    svc.run(SEASON, entities=("players",))
    p3 = p_repo.get_by_external_id(ExternalId("P3"))
    assert p3.name is None
    # resolver now has an official name for P3
    svc2 = CatalogBackfillService(
        p_repo, _teams(), stats,
        player_names=_MapResolver({"P3": "CARLOS"}),
    )
    result = svc2.run(SEASON, entities=("players",))
    assert result.updated == 1
    assert p_repo.get_by_external_id(ExternalId("P3")).name == "CARLOS"


def _teams():
    return InMemoryTeamRepository()


def test_players_preserve_existing_name_on_conflict():
    svc, _, p_repo, _ = _build()
    p_repo.save(Player(external_id=ExternalId("P1"), player_id=PlayerId(str(uuid4())),
                       name="NOMBRE EXISTENTE"))
    result = svc.run(SEASON, entities=("players",))
    assert result.warnings == ["P1: keeping existing name 'NOMBRE EXISTENTE' (official candidate 'JUAN')"]
    assert p_repo.get_by_external_id(ExternalId("P1")).name == "NOMBRE EXISTENTE"
    assert result.created == 3  # P2..P4 still created


def test_players_single_catalog_entity_across_matches():
    svc, _, p_repo, _ = _build()
    svc.run(SEASON, entities=("players",))
    # P1 appears in both M1 and M2 -> a single catalog record
    hits = [p for p in p_repo.search_by_name("JUAN")]
    assert len(hits) == 1 and str(hits[0].external_id) == "P1"


def test_players_season_isolation():
    stats = InMemoryMatchStatsRepository()
    stats.save_player_stats("MX", SEASON, [_ps("P1", "T1")])
    stats.save_player_stats("MY", SeasonCode("2024-2025"), [_ps("PX", "T9")])
    p_repo = InMemoryPlayerRepository()
    svc = CatalogBackfillService(
        p_repo, InMemoryTeamRepository(), stats,
        player_names=_MapResolver({"P1": "JUAN"}),
    )
    svc.run(SEASON, entities=("players",))
    assert p_repo.get_by_external_id(ExternalId("PX")) is None  # other season ignored


def test_dry_run_writes_nothing():
    """--dry-run must plan without persisting (idempotent, zero side effects)."""
    svc, _, p_repo, t_repo = _build()
    result = svc.run(SEASON, dry_run=True)
    assert result.created == 7 and result.errors == 0  # 4 players + 3 teams
    # nothing materialized in the catalog
    assert p_repo.get_by_external_id(ExternalId("P4")) is None
    assert t_repo.get_by_external_id(ExternalId("T3")) is None
    # a real run afterwards still works and produces the same plan
    again = svc.run(SEASON)
    assert again.created == 7


# ===========================================================================
# Teams
# ===========================================================================


def test_teams_create_unknown_entities():
    svc, _, _, t_repo = _build()
    result = svc.run(SEASON, entities=("teams",))
    assert result.created == 3  # T1..T3
    assert t_repo.get_by_external_id(ExternalId("T1")).name == "CLUB UNO"
    assert t_repo.get_by_external_id(ExternalId("T2")).name is None


def test_teams_no_duplicate_and_conflict_policy():
    svc, _, _, t_repo = _build()
    t_repo.save(Team(external_id=ExternalId("T1"), team_id=TeamId(str(uuid4())),
                     name="EXISTENTE"))
    result = svc.run(SEASON, entities=("teams",))
    assert t_repo.get_by_external_id(ExternalId("T1")).name == "EXISTENTE"
    assert result.skipped == 1
    assert any("keeping existing name" in w for w in result.warnings)
    again = svc.run(SEASON, entities=("teams",))
    assert again.created == 0 and again.updated == 0 and again.skipped == 3


# ===========================================================================
# Replay / invariants
# ===========================================================================


def test_replay_keeps_stats_and_matches_identical():
    svc, stats, _, _ = _build()
    player_stats_before = list(stats.list_player_stats("M1"))
    team_stats_before = list(stats.list_team_stats("M1"))
    svc.run(SEASON)
    svc.run(SEASON)
    assert list(stats.list_player_stats("M1")) == player_stats_before
    assert list(stats.list_team_stats("M1")) == team_stats_before


def test_replay_preserves_entity_ids():
    svc, _, p_repo, t_repo = _build()
    svc.run(SEASON)
    first_id = str(p_repo.get_by_external_id(ExternalId("P1")).player_id)
    first_tid = str(t_repo.get_by_external_id(ExternalId("T1")).team_id)
    svc.run(SEASON)
    assert str(p_repo.get_by_external_id(ExternalId("P1")).player_id) == first_id
    assert str(t_repo.get_by_external_id(ExternalId("T1")).team_id) == first_tid