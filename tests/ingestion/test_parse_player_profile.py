"""Public player profile (Jugador.aspx) → PlayerBio.

Proves the bio fields the match boxscore never carries are parsed from the
public profile, and that a blank profile degrades to an empty bio instead of
raising or inventing values.
"""
from __future__ import annotations

import importlib.util
import sys as _sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests/ingestion/fixtures"

_spec = importlib.util.spec_from_file_location(
    "parse_player_profile", ROOT / "scripts" / "feb" / "parse_player_profile.py"
)
PP = importlib.util.module_from_spec(_spec)
_sys.modules[_spec.name] = PP
_spec.loader.exec_module(PP)


def _bio(fixture: str, pid: str):
    return PP.parse_player_profile((FIX / f"{fixture}.html").read_text(encoding="utf-8"), pid)


def test_parses_a_full_profile():
    b = _bio("jugador_1568569", "1568569")
    assert b.name == "JUANOLA MADERA, JORDI"
    assert b.position == "Alero"
    assert b.height_cm == 196
    assert b.nationality == "ESPAÑA"
    assert not b.is_empty


def test_splits_birth_date_from_birth_city():
    b = _bio("jugador_1568569", "1568569")
    assert b.birth_date == date(1998, 4, 11)
    assert b.birth_place == "Barcelona"


def test_blank_profile_yields_an_empty_bio():
    """FEB publishes some profiles with every field empty — that must not raise,
    and must not pick up neighbouring markup (the team name sits right after the
    empty name div)."""
    b = _bio("jugador_2436640", "2436640")
    assert b.is_empty
    assert b.name is None          # not the team name that follows it
    assert b.height_cm is None
    assert b.nationality is None


def test_weight_is_never_parsed():
    """FEB always publishes '- Kg', so weight is deliberately not a field."""
    assert not hasattr(_bio("jugador_1568569", "1568569"), "weight_kg")


def test_missing_height_is_none_not_zero():
    assert PP.parse_player_profile('<span class="label">Altura</span>'
                                   '<span class="string">- cm</span>', "x").height_cm is None
