"""Photo-less hero card — the account must not depend on player photos.

The point of stat_hero is that a great card exists with NO photo: the number is
the protagonist and the crest is an optional identity echo. So it must render
valid SVG carrying the number, the name and the label, WITH or WITHOUT a crest.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from feb_score.infrastructure.rendering.component_templates import render_template


def _data(**facts_over):
    facts = {
        "section_label": "Máximo anotador de la temporada",
        "hero_value": 524, "hero_label": "PUNTOS TOTALES",
        "secondary": [[26, "PART"], ["20,2", "PPP"]], "rating": None,
    }
    facts.update(facts_over)
    return {
        "story": {"story_type": "top_scorer", "season_code": "2025-2026",
                  "round_number": 26, "facts": facts},
        "display": {"player": "Kyle Jonathan Greeley", "team": "UPB Gandia"},
        "assets": {}, "copy": {},
    }


def test_renders_valid_svg_without_any_photo_or_crest():
    svg = render_template("stat_hero", _data())
    ET.fromstring(svg)                       # parses = well-formed
    assert "524" in svg                      # the hero number is present
    assert "GREELEY" in svg.upper()
    assert "PUNTOS TOTALES" in svg.upper()
    assert "{{" not in svg                   # no un-substituted placeholder


def test_the_crest_is_optional_identity_not_required():
    without = render_template("stat_hero", _data())
    d = _data(); d["assets"]["team_crest"] = "data:image/png;base64,AAAA"
    with_crest = render_template("stat_hero", d)
    # the court background is an <image>, so key off the crest's identity group
    assert 'opacity="0.14"' not in without   # no crest supplied -> no identity echo
    assert 'opacity="0.14"' in with_crest    # crest shows as the faint identity


def test_a_long_number_still_fits():
    svg = render_template("stat_hero", _data(hero_value=1234, hero_label="MINUTOS"))
    ET.fromstring(svg)
    assert "1234" in svg
