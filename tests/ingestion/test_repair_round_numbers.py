"""FASE 22.4 — Historical round-number repair tests (offline, mocks).

No FEB real, no API real, no production. El discovery del calendario se simula
monkeypatcheando `R.IS.discover_rounds` (que es la única fuente de verdad usada).
"""
from __future__ import annotations

import importlib.util
import sys as _sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location(
    "repair_round_numbers", ROOT / "scripts" / "feb" / "repair_round_numbers.py"
)
R = importlib.util.module_from_spec(_spec)
_sys.modules[_spec.name] = R
_spec.loader.exec_module(R)

SEASON = "2025-2026"


def _match_ref(ext, rn):
    return R.DM.MatchRef(
        external_id=ext,
        round_number=rn,
        scheduled_at="2025-10-04T00:00:00+01:00",
        home_team=f"H{ext}",
        away_team=f"A{ext}",
        source_url=f"https://baloncestoenvivo.feb.es/Partido.aspx?p={ext}",
    )


def _by_round():
    return {
        1: [_match_ref(2486849, 1), _match_ref(2486850, 1), _match_ref(2486851, 1)],
        2: [_match_ref(2486852, 2), _match_ref(2486853, 2)],
    }


def _patch_discovery(monkeypatch, by_round=None):
    monkeypatch.setattr(R.IS, "discover_rounds", lambda season, group: by_round or _by_round())


# --- 1. construye el mapeo external_id -> round real desde discovery
def test_build_round_map_from_discovery(monkeypatch):
    _patch_discovery(monkeypatch)
    mapping = R.build_round_map(SEASON)
    assert mapping == {
        "2486849": 1, "2486850": 1, "2486851": 1,
        "2486852": 2, "2486853": 2,
    }


# --- 2. el SQL generado es idempotente y solo toca round_number
def test_render_sql_idempotent_and_targeted():
    sql = R.render_sql({"2486849": 7, "2486852": 2})
    assert len(sql) == 2
    for stmt in sql:
        assert "UPDATE matches" in stmt
        assert "jsonb_set(data, '{round_number}'" in stmt
        assert "WHERE external_id =" in stmt
        assert "IS DISTINCT FROM" in stmt  # guarda: re-ejecutar = no-op
        assert "match_player_stats" not in stmt
        assert "match_team_stats" not in stmt
        assert "DELETE" not in stmt
        assert "INSERT" not in stmt


def test_render_sql_contains_correct_round_values():
    sql = "\n".join(R.render_sql({"2486849": 7, "2486850": 1}))
    assert "WHERE external_id = '2486849'" in sql
    assert "'7'::jsonb" in sql
    assert "data->>'round_number' IS DISTINCT FROM '7'" in sql
    assert "WHERE external_id = '2486850'" in sql
    assert "'1'::jsonb" in sql


def test_render_sql_empty_map_no_statements():
    assert R.render_sql({}) == []


# --- 3. determinismo del mapeo (mismo calendario -> mismo orden)
def test_build_round_map_deterministic(monkeypatch):
    _patch_discovery(monkeypatch)
    a = list(R.build_round_map(SEASON).items())
    b = list(R.build_round_map(SEASON).items())
    assert a == b
    assert list(dict(a)) == sorted(dict(a))  # orden por external_id


# --- 4. dry-run no emite SQL
def test_cli_dry_run_no_sql(monkeypatch, capsys):
    _patch_discovery(monkeypatch)
    monkeypatch.setattr(_sys, "argv", [
        "repair_round_numbers.py", "--season", SEASON, "--dry-run",
    ])
    rc = R.run()
    out = capsys.readouterr().out
    assert rc == 0
    assert "mapped=5" in out
    assert "DRY_RUN: no SQL emitted" in out
    assert "UPDATE matches" not in out


# --- 5. CLI emite SQL por stdout (para psql vía túnel)
def test_cli_emits_sql(monkeypatch, capsys):
    _patch_discovery(monkeypatch)
    monkeypatch.setattr(_sys, "argv", [
        "repair_round_numbers.py", "--season", SEASON,
    ])
    rc = R.run()
    out = capsys.readouterr().out
    assert rc == 0
    assert "mapped=5" in out
    assert out.count("UPDATE matches") == 5
    assert "psql" in out  # instrucción de aplicación documentada


# --- 6. config inválida -> exit 2; fuente fallida -> exit 3
def test_cli_exit_2_bad_season(monkeypatch, capsys):
    monkeypatch.setattr(_sys, "argv", [
        "repair_round_numbers.py", "--season", "2024-2025",
    ])
    assert R.run() == 2
    assert "CONFIG_ERROR" in capsys.readouterr().err


def test_cli_exit_3_discovery_failed(monkeypatch, capsys):
    monkeypatch.setattr(
        R.IS, "discover_rounds",
        lambda season, group: (_ for _ in ()).throw(R.DM.SourceError("calendar down")),
    )
    monkeypatch.setattr(_sys, "argv", [
        "repair_round_numbers.py", "--season", SEASON,
    ])
    assert R.run() == 3
    assert "SOURCE_ERROR" in capsys.readouterr().err


# --- 7. reutiliza la lógica existente (no duplica discovery)
def test_repair_reuses_existing_logic():
    assert R.IS.discover_rounds.__module__ == "ingest_season"
    assert R.DM.fetch_calendar.__module__ == "discover_matches"
    for name in ("fetch_calendar", "parse_calendar", "discover_matches"):
        assert not hasattr(R, name), f"repair duplica {name}"