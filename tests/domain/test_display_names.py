"""The display-name standard: NOMBRE APELLIDOS."""
from __future__ import annotations

import pytest

from feb_score.domain.content.names import (
    display_name,
    is_abbreviated,
    prefer_fuller_name,
)


@pytest.mark.parametrize("source,expected", [
    # the real shapes FEB serves, sampled from production
    ("SAMAR, MATIJA", "MATIJA SAMAR"),
    ("RUESGA, FAUSTO", "FAUSTO RUESGA"),
    ("JUANOLA MADERA, JORDI", "JORDI JUANOLA MADERA"),
    ("BRACEY, LYSANDER AMEEN", "LYSANDER AMEEN BRACEY"),
    ("MAYS JR, MICHAEL LEE", "MICHAEL LEE MAYS JR"),   # suffix stays with surnames
])
def test_reorders_surnames_first_names(source, expected):
    assert display_name(source) == expected


def test_never_expands_an_initial():
    """Turning 'J.' into a given name would be inventing one."""
    assert display_name("J. JUANOLA MADERA") == "J. JUANOLA MADERA"
    assert display_name("N. DEDOVIC") == "N. DEDOVIC"


def test_preserves_casing_for_the_template_to_decide():
    assert display_name("Samar, Matija") == "Matija Samar"


@pytest.mark.parametrize("value", [None, "", "   "])
def test_blank_stays_falsy_so_callers_can_fall_back(value):
    assert not display_name(value)


def test_tolerates_messy_input():
    assert display_name("  SAMAR ,  MATIJA  ") == "MATIJA SAMAR"
    assert display_name("SOLO NOMBRE") == "SOLO NOMBRE"
    assert display_name("SAMAR,") == "SAMAR,"        # a stray comma is not a name
    assert display_name(", MATIJA") == ", MATIJA"


class TestPreferFuller:
    def test_full_name_upgrades_an_initial(self):
        assert prefer_fuller_name("J. JUANOLA MADERA", "JUANOLA MADERA, JORDI") \
            == "JUANOLA MADERA, JORDI"

    def test_never_churns_an_already_good_name(self):
        assert prefer_fuller_name("SAMAR, MATIJA", "SAMAR, M") == "SAMAR, MATIJA"
        assert prefer_fuller_name("SAMAR, MATIJA", "OTRO, NOMBRE") == "SAMAR, MATIJA"

    def test_fills_a_missing_name(self):
        assert prefer_fuller_name(None, "SAMAR, MATIJA") == "SAMAR, MATIJA"
        assert prefer_fuller_name("SAMAR, MATIJA", None) == "SAMAR, MATIJA"


def test_is_abbreviated_detects_the_initial_form():
    assert is_abbreviated("J. JUANOLA MADERA")
    assert is_abbreviated("J.M. LOPEZ")
    assert not is_abbreviated("JORDI JUANOLA")
    assert not is_abbreviated("JUANOLA MADERA, JORDI")
