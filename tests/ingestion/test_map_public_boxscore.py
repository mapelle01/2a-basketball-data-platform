"""Public boxscore → upsert_match_stats command mapper.

Proves the scraped boxscore maps to a schema-valid ingest command carrying
per-player shooting/fouls/+/-, that team totals aggregate from the player rows,
and that the handler reconstructs a PlayerStats with those fields.
"""
from __future__ import annotations

import importlib.util
import sys as _sys
from pathlib import Path

import pytest

from feb_score.application.validation import validate_command
from feb_score.application.use_cases.handlers import UpsertMatchStatsHandler

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests/ingestion/fixtures"

_spec = importlib.util.spec_from_file_location(
    "parse_public_boxscore", ROOT / "scripts" / "feb" / "parse_public_boxscore.py"
)
M = importlib.util.module_from_spec(_spec)
_sys.modules[_spec.name] = M
_spec.loader.exec_module(M)

SEASON = "2025-2026"
COMP = "segundafeb"
SCHEMA = "commands/upsert_match_stats.v1.json"


def _command(match_id="2486849", played_at=None):
    box = M.parse_public_boxscore((FIX / f"partido_{match_id}.html").read_text(encoding="utf-8"), match_id)
    return box, M.to_stats_command(box, SEASON, COMP, played_at=played_at)


def test_command_is_schema_valid():
    _, cmd = _command()
    validate_command(cmd, SCHEMA)  # raises if the shooting fields break the contract


def test_command_is_idempotent():
    _, a = _command()
    _, b = _command()
    assert a["command_id"] == b["command_id"] == M._stats_command_id(SEASON, COMP, "2486849")


def test_player_stats_carry_shooting():
    _, cmd = _command()
    row = next(p for p in cmd["payload"]["player_stats"] if p["player_external_id"] == "1549741")
    assert row["team_external_id"] == "981514"
    assert (row["points"], row["rebounds"], row["assists"]) == (11, 4, 1)
    assert (row["three_points_made"], row["three_points_attempted"]) == (2, 4)
    assert (row["field_goals_made"], row["field_goals_attempted"]) == (4, 9)
    assert (row["free_throws_made"], row["free_throws_attempted"]) == (1, 4)
    assert row["fouls"] == 2 and row["plus_minus"] == -10


def test_team_totals_aggregate_from_players():
    box, cmd = _command()
    home = cmd["payload"]["home_team_stats"]
    home_players = box.players_of(box.home.external_id)
    assert home["points_for"] == box.home.score == 78
    assert home["points_against"] == box.away.score == 66
    assert home["three_points_made"] == sum(p.three_points.made for p in home_players)
    assert home["field_goals_attempted"] == sum(p.field_goals.attempted for p in home_players)
    assert home["rebounds"] == sum(p.rebounds_total for p in home_players)


def test_handler_reconstructs_playerstats_with_shooting():
    _, cmd = _command()
    row = next(p for p in cmd["payload"]["player_stats"] if p["player_external_id"] == "1549741")
    ps = UpsertMatchStatsHandler._player_stats(row)
    assert ps.three_points_made == 2 and ps.three_points_attempted == 4
    assert ps.field_goals_made == 4 and ps.free_throws_attempted == 4
    assert ps.fouls == 2 and ps.plus_minus == -10


def test_old_match_also_maps_and_validates():
    _, cmd = _command("29232")  # 2005-06
    validate_command(cmd, SCHEMA)
    assert any(r["three_points_attempted"] for r in cmd["payload"]["player_stats"])
