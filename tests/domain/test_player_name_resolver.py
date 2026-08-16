"""FASE 24.2 — OfficialPlayerNameResolver unit tests (offline).

Verifies ``player_external_id -> official_name`` resolution from the real FEB
BoxScore payload (reusing ``ingest_match.parse_boxscore``), plus the backfill
service contract: no-overwrite on conflict, no-op when already named,
fail-closed on missing token, dry-run writes nothing, and that the token never
appears in any user-facing string. Offline only: a fixture boxscore loader is
injected (no network, no FEB_TOKEN printed/logged).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "ingestion" / "fixtures" / "boxscore_2486864.json"

_spec_backfill = importlib.util.spec_from_file_location(
    "backfill_catalog", ROOT / "scripts" / "feb" / "backfill_catalog.py"
)
B = importlib.util.module_from_spec(_spec_backfill)
sys.modules[_spec_backfill.name] = B
_spec_backfill.loader.exec_module(B)

from feb_score.application.repositories.in_memory import (
    InMemoryMatchStatsRepository,
    InMemoryPlayerRepository,
    InMemoryTeamRepository,
)
from feb_score.application.use_cases.catalog_backfill_service import CatalogBackfillService
from feb_score.application.use_cases.player_name_resolver import (
    OfficialPlayerNameResolver,
    SourceError,
)
from feb_score.domain.player.model import Player
from feb_score.domain.statistics.model import PlayerStats
from feb_score.domain.value_objects import ExternalId, PlayerId, SeasonCode

SEASON = SeasonCode("2025-2026")


def _load_fixture(box_path):
    box = json.loads(box_path.read_text(encoding="utf-8"))
    from feb_score.application.use_cases.player_name_resolver import _import_feb
    ingest = _import_feb()
    return ingest.parse_boxscore(box, match_id="2486864", season_code=str(SEASON))


def _fixture_names(box_path):
    return OfficialPlayerNameResolver._extract_names(_load_fixture(box_path))


def _seeded_stats(player_ids):
    """One InMemory stats repo seeded with one stat row per player (so aggregates
    enumerate exactly `player_ids`), shared with the resolver + service."""
    stats = InMemoryMatchStatsRepository()
    rows = [
        PlayerStats(player_external_id=pid, team_external_id="T-HOME",
                    points=1, rebounds=0, assists=0, steals=0, blocks=0,
                    turnovers=0, minutes=1.0)
        for pid in player_ids
    ]
    stats.save_player_stats("M-TEST", SEASON, rows)
    return stats


class _FixtureMatchRepo:
    def __init__(self, match_id):
        self._id = match_id

    def search(self, season_code):
        from collections import namedtuple
        M = namedtuple("M", ["external_id", "home_team_id", "away_team_id"])
        return [M(self._id, "T-HOME", "T-AWAY")]


def _resolver(stats_repo, match_id="2486864", token="test-token"):
    def _loader(mid, t):
        # token passed through but never stored/returned/serialized
        return _load_fixture(FIXTURE)
    return OfficialPlayerNameResolver(
        _FixtureMatchRepo(match_id), stats_repo, str(SEASON),
        token=token, boxscore_loader=_loader,
    )


def test_resolve_finds_official_names_from_boxscore():
    pids = list(_fixture_names(FIXTURE).keys())
    stats = _seeded_stats(pids)
    res = _resolver(stats)
    names = res.resolve(SEASON)
    assert names["2772828"] == "F. ANDRADE AMIEL"
    assert names["2151562"] == "O. THIAM PEDRERA"
    r, u, c = res.last_stats()
    assert r == len(pids) and u == 0 and c == 0


def test_resolve_marks_unresolved_targets_as_null_not_dropped():
    pids = list(_fixture_names(FIXTURE).keys()) + ["99999999-UNKNOWN"]
    stats = _seeded_stats(pids)
    res = _resolver(stats)
    names = res.resolve(SEASON)
    assert names["99999999-UNKNOWN"] is None
    r, u, c = res.last_stats()
    assert r == len(_fixture_names(FIXTURE)) and u == 1


def test_fail_closed_without_token_never_invents():
    pids = list(_fixture_names(FIXTURE).keys())
    stats = _seeded_stats(pids)
    res = OfficialPlayerNameResolver(_FixtureMatchRepo("x"), stats, str(SEASON))
    with pytest.raises(SourceError):
        res.resolve(SEASON)
    r, u, c = res.last_stats()
    assert r == 0 and u == len(pids)  # fail-closed diagnostic


def test_backfill_no_op_when_already_named():
    pids = list(_fixture_names(FIXTURE).keys())
    repo = InMemoryPlayerRepository()
    for pid in pids:
        repo.save(Player(external_id=ExternalId(pid), player_id=PlayerId(str(uuid4())),
                         name="EXISTING NAME"))
    stats = _seeded_stats(pids)
    res = _resolver(stats)
    svc = CatalogBackfillService(repo, InMemoryTeamRepository(), stats, player_names=res)
    result = svc.run(SEASON, entities=("players",))
    assert result.created == 0 and result.updated == 0 and result.skipped == len(pids)
    assert repo.get_by_external_id(ExternalId(pids[0])).name == "EXISTING NAME"
    assert any("keeping existing name" in w for w in result.warnings)


def test_backfill_conflict_not_silently_overwritten():
    pids = list(_fixture_names(FIXTURE).keys())
    repo = InMemoryPlayerRepository()
    conflict_pid = pids[0]
    repo.save(Player(external_id=ExternalId(conflict_pid), player_id=PlayerId(str(uuid4())),
                     name="DIFFERENT EXISTING"))
    stats = _seeded_stats(pids)
    res = _resolver(stats)
    svc = CatalogBackfillService(repo, InMemoryTeamRepository(), stats, player_names=res)
    result = svc.run(SEASON, entities=("players",))
    saved = repo.get_by_external_id(ExternalId(conflict_pid))
    assert saved.name == "DIFFERENT EXISTING"  # preserved, NOT overwritten
    assert any(conflict_pid in w and "keeping existing name" in w for w in result.warnings)


def test_dry_run_writes_nothing_but_reports_plan():
    pids = list(_fixture_names(FIXTURE).keys())
    repo = InMemoryPlayerRepository()
    stats = _seeded_stats(pids)
    res = _resolver(stats)
    svc = CatalogBackfillService(repo, InMemoryTeamRepository(), stats, player_names=res)
    result = svc.run(SEASON, entities=("players",), dry_run=True)
    assert result.created == len(pids)  # planned, not persisted
    assert repo.get_by_external_id(ExternalId(pids[0])) is None  # nothing written


def test_token_never_appears_in_strings_or_exceptions():
    pids = list(_fixture_names(FIXTURE).keys())
    stats = _seeded_stats(pids)
    res = _resolver(stats, token="SUPER_SECRET_TOKEN_VALUE")
    names = res.resolve(SEASON)
    assert "SUPER_SECRET_TOKEN_VALUE" not in json.dumps(names)
    assert "SUPER_SECRET_TOKEN_VALUE" not in repr(res.last_stats())
