"""The age lanes — youngest and veteran of the round.

Age is the best-populated bio field (443/443 players in 2024-25), and it says
something a scoreboard never does: a 16-year-old dropped 21, a 41-year-old
scored 13. Age is the hook, so it is the hero number; the game sits beside it.
Computed against the ROUND's date so a backfilled card is truthful and stable.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date, datetime

from feb_score.domain.content.bio import LeagueBio
from feb_score.domain.content.copy import generate_copy
from feb_score.domain.content.insights import (
    AGE_CURIO_MIN_POINTS,
    VETERAN_MIN_AGE,
    YOUNG_GUN_MAX_AGE,
    MatchFactsInput,
    PlayerLineInput,
    detect_veteran,
    detect_young_gun,
)
from feb_score.domain.content.registry import DetectionContext, Scope, run_detectors
from feb_score.domain.content.story import STORY_TO_TEMPLATE, StoryType
from feb_score.domain.content.validation import validate_copy
from feb_score.infrastructure.rendering.component_templates import render_template

ROUND_DATE = datetime(2025, 3, 1, 18, 0)


def _match():
    return MatchFactsInput("m1", "2024-2025", 20, "tA", "tB", "A", "B", 80, 70, ROUND_DATE)


def _line(pid, points=15, name=None):
    return PlayerLineInput(pid, name or pid.upper(), "t1", "Equipo", "m1",
                           points=points, rebounds=5, assists=2, steals=1, blocks=0,
                           turnovers=2, minutes=28.0)


def _born(year):
    return f"{year}-09-01"   # birthday after the March round date


class TestAgeOn:
    def test_computes_full_years_against_the_reference(self):
        bio = LeagueBio(birth_by_player={"p": "2000-06-15"})
        assert bio.age_on("p", date(2025, 3, 1)) == 24    # birthday not yet reached
        assert bio.age_on("p", date(2025, 7, 1)) == 25    # birthday passed

    def test_missing_or_unparseable_birth_is_none_not_a_guess(self):
        bio = LeagueBio(birth_by_player={"bad": "not-a-date"})
        assert bio.age_on("bad", date(2025, 3, 1)) is None
        assert bio.age_on("absent", date(2025, 3, 1)) is None


class TestYoungGun:
    def _bio(self):
        return LeagueBio(birth_by_player={"kid": _born(2008), "mid": _born(2000), "vet": _born(1985)})

    def test_skips_without_dates_or_a_round_date(self):
        assert detect_young_gun("2024-2025", 20, [_line("kid")], None, [_match()]) is None
        assert detect_young_gun("2024-2025", 20, [_line("kid")], self._bio(), []) is None

    def test_crowns_the_youngest_with_a_real_game(self):
        s = detect_young_gun("2024-2025", 20,
                             [_line("kid", 18), _line("mid", 30)], self._bio(), [_match()])
        assert s.story_type is StoryType.YOUNG_GUN
        assert s.facts["player_external_id"] == "kid"
        assert s.facts["age"] == 16
        # age is the hero, the game sits beside it
        assert s.facts["hero_value"] == 16 and s.facts["hero_label"] == "AÑOS"
        assert s.facts["secondary"] == [[18, "PTS"], [5, "REB"]]

    def test_a_quiet_night_does_not_qualify(self):
        assert AGE_CURIO_MIN_POINTS == 12
        s = detect_young_gun("2024-2025", 20,
                             [_line("kid", AGE_CURIO_MIN_POINTS - 1)], self._bio(), [_match()])
        assert s is None

    def test_an_of_age_player_is_not_a_prospect(self):
        assert YOUNG_GUN_MAX_AGE == 20
        # only the 25-year-old scores enough; being older than the bound, no card
        s = detect_young_gun("2024-2025", 20, [_line("mid", 25)], self._bio(), [_match()])
        assert s is None

    def test_runs_under_the_bio_scope(self):
        ctx = DetectionContext("2024-2025", 20, player_lines=(_line("kid", 20),),
                               matches=(_match(),), bio=self._bio())
        assert StoryType.YOUNG_GUN in {s.story_type for s in run_detectors(ctx, {Scope.BIO})}


class TestVeteran:
    def _bio(self):
        return LeagueBio(birth_by_player={"old": _born(1984), "mid": _born(2000)})

    def test_crowns_the_oldest_with_a_real_game(self):
        s = detect_veteran("2024-2025", 20,
                           [_line("old", 13), _line("mid", 30)], self._bio(), [_match()])
        assert s.story_type is StoryType.VETERAN
        assert s.facts["player_external_id"] == "old"
        assert s.facts["age"] == 40

    def test_a_merely_seasoned_player_is_not_a_veteran(self):
        assert VETERAN_MIN_AGE == 34
        s = detect_veteran("2024-2025", 20, [_line("mid", 30)], self._bio(), [_match()])
        assert s is None


class TestCopy:
    def test_young_gun_numbers_trace_and_agree(self):
        bio = LeagueBio(birth_by_player={"kid": _born(2008)})
        s = detect_young_gun("2024-2025", 20, [_line("kid", 21, "MITEO, MERVEDI")], bio, [_match()])
        c = generate_copy({"story_type": "young_gun", "round_number": 20, "facts": s.facts})
        assert validate_copy(c.to_dict(), {**s.facts, "round_number": 20}).ok
        assert "16 años" in c.caption and "21 puntos" in c.caption
        assert c.headline == "MERVEDI MITEO"

    def test_singular_year_agrees(self):
        bio = LeagueBio(birth_by_player={"kid": "2024-01-01"})
        s = detect_young_gun("2024-2025", 20, [_line("kid", 15)], bio,
                             [MatchFactsInput("m1", "2024-2025", 20, "tA", "tB", "A", "B",
                                              80, 70, datetime(2025, 6, 1))])
        # a contrived 1-year-old only exercises the grammar branch
        c = generate_copy({"story_type": "young_gun", "round_number": 20, "facts": s.facts})
        assert "1 año," in c.caption and "1 años" not in c.caption


class TestCard:
    def test_both_have_their_own_headline_and_render(self):
        assert STORY_TO_TEMPLATE[StoryType.YOUNG_GUN] == "player_of_round"
        assert STORY_TO_TEMPLATE[StoryType.VETERAN] == "player_of_round"
        bio = LeagueBio(birth_by_player={"kid": _born(2008)})
        s = detect_young_gun("2024-2025", 20, [_line("kid", 21, "MITEO, MERVEDI")], bio, [_match()])
        svg = render_template("player_of_round", {
            "story": {"facts": s.facts, "round_number": 20, "season_code": "2024-2025",
                      "story_type": s.story_type.value},
            "display": {"player": s.facts["player_name"], "team": "Zunder Palencia"},
            "assets": {"player_initials": "MM"}, "copy": {}, "meta": {},
        })
        ET.fromstring(svg)
        assert "LA JOVEN PROMESA" in svg
        assert ">16<" in svg and ">AÑOS<" in svg
