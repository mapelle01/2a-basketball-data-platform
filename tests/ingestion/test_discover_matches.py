"""FASE 22.1 — Match Discovery tests against a controlled calendar fixture.

Offline only: reads tests/ingestion/fixtures/calendario_jornadas_2025_2026.html.
No network, no FEB token, no API key, no production POST in these tests.
"""
from __future__ import annotations

import importlib.util
import sys as _sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = (ROOT / "tests/ingestion/fixtures/calendario_jornadas_2025_2026.html").read_text(
    encoding="utf-8"
)

_spec = importlib.util.spec_from_file_location(
    "discover_matches", ROOT / "scripts" / "feb" / "discover_matches.py"
)
M = importlib.util.module_from_spec(_spec)
_sys.modules[_spec.name] = M
_spec.loader.exec_module(M)

SEASON = "2025-2026"
Round = M.MatchRef


def _round(n):
    return M.discover_matches(SEASON, n, calendar_html=FIXTURE)


# --- 1. descubre partidos de una jornada
def test_discovers_matches_for_round():
    refs = _round(1)
    assert isinstance(refs, list)
    assert len(refs) == 3
    assert all(isinstance(r, Round) for r in refs)


# --- 2. external_id (match_id FEB de Partido.aspx?p=)
def test_external_id_is_match_id():
    refs = _round(1)
    assert {r.external_id for r in refs} == {2486849, 2486850, 2486851}


# --- 3. round_number
def test_round_number():
    assert {r.round_number for r in _round(1)} == {1}
    assert {r.round_number for r in _round(2)} == {2}


# --- 4. scheduled_at (fecha de jornada a medianoche +01:00)
def test_scheduled_at_from_jornada_date():
    by_id = {r.external_id: r for r in _round(1)}
    assert by_id[2486849].scheduled_at == "2025-10-04T00:00:00+01:00"
    by_id2 = {r.external_id: r for r in _round(2)}
    assert by_id2[2486852].scheduled_at == "2025-10-11T00:00:00+01:00"


# --- 5. home_team / away_team
def test_teams_home_away():
    by_id = {r.external_id: r for r in _round(1)}
    assert by_id[2486851].home_team == "BUENO ARENAS ALBACETE BASKET"
    assert by_id[2486851].away_team == "SOL GIRONÈS BISBAL BÀSQUET"
    assert by_id[2486850].home_team == "HOMS U.E.MATARÓ"
    assert by_id[2486850].away_team == "CLASS BASQUET SANT ANTONI"


# --- 6. dedupe de IDs repetidos dentro de la jornada
def test_dedupe_repeated_match_ids():
    refs = _round(1)
    assert len(refs) == len({r.external_id for r in refs})
    assert len([r for r in refs if r.external_id == 2486849]) == 1


# --- 7. filtro por jornada (round)
def test_filters_by_round():
    assert {r.external_id for r in _round(1)} == {2486849, 2486850, 2486851}
    assert {r.external_id for r in _round(2)} == {2486852, 2486853}


# --- 8. filas inválidas ignoradas sin abortar la jornada
def test_invalid_rows_skipped():
    assert "999991" not in {str(r.external_id) for r in _round(1)}
    refs = _round(1)  # sigue devolviendo los válidos
    assert len(refs) == 3


# --- extras: determinismo y source_url
def test_sorted_by_external_id():
    ids = [r.external_id for r in _round(1)]
    assert ids == sorted(ids)


def test_source_url_points_to_partido():
    assert _round(1)[0].source_url == "https://baloncestoenvivo.feb.es/Partido.aspx?p=2486849"


# --- configuración inválida -> ConfigError (CLI devuelve código 2)
@pytest.mark.parametrize("season", ["2024-2025", "2026-2027", "2025"])
def test_unsupported_season_raises(season):
    with pytest.raises(M.ConfigError):
        M.discover_matches(season, 1, calendar_html=FIXTURE)


@pytest.mark.parametrize("r", [0, -1, "1", 1.5])
def test_invalid_round_raises(r):
    with pytest.raises(M.ConfigError):
        M.discover_matches(SEASON, r, calendar_html=FIXTURE)


# --- fuente no parseable -> SourceError (CLI devuelve código 3)
def test_source_error_when_no_jornadas():
    with pytest.raises(M.SourceError):
        M.discover_matches(SEASON, 1, calendar_html="<html><body>no calendar</body></html>")