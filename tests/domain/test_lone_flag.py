"""The BIO lane — the first cards that need more than a boxscore.

Every other detector ranks a column, which is the one thing a scoreboard
already does. This one reads the roster: Segunda FEB fields 53 nationalities in
a season and 27 of them have exactly one player, which is a fact no results
page can tell you.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from feb_score.domain.content.bio import LeagueBio
from feb_score.domain.content.copy import generate_copy
from feb_score.domain.content.insights import (
    LONE_FLAG_MIN_POINTS,
    PlayerLineInput,
    detect_lone_flag,
)
from feb_score.domain.content.registry import DetectionContext, Scope, run_detectors
from feb_score.domain.content.story import STORY_TO_TEMPLATE, StoryType
from feb_score.domain.content.validation import validate_copy
from feb_score.infrastructure.rendering.component_templates import render_template


def _line(pid, points=20, name=None, **kw):
    base = dict(rebounds=6, assists=2, steals=1, blocks=0, turnovers=2, minutes=30.0,
                field_goals_made=8, field_goals_attempted=15, three_points_made=2,
                three_points_attempted=5, free_throws_made=2, free_throws_attempted=3,
                fouls=2, fouls_received=3)
    base.update(kw)
    return PlayerLineInput(pid, name or pid.upper(), "t1", "Equipo", "m1",
                           points=points, **base)


_BIO = LeagueBio({"solo": "BENIN", "a": "ESPAÑA", "b": "ESPAÑA", "c": "SENEGAL", "d": "SENEGAL"})


class TestLeagueBio:
    def test_counts_are_season_wide(self):
        assert _BIO.countrymen("solo") == 1
        assert _BIO.countrymen("a") == 2
        assert _BIO.countries == 3

    def test_only_one_means_only_one(self):
        assert _BIO.is_sole_representative("solo")
        assert not _BIO.is_sole_representative("c")

    def test_a_player_with_no_nationality_is_not_rare(self):
        """Absence of data is not evidence of rarity — the card would otherwise
        claim uniqueness for anyone the backfill missed."""
        assert _BIO.countrymen("unknown") is None
        assert not _BIO.is_sole_representative("unknown")

    def test_empty_bio_is_falsy_so_detectors_skip(self):
        assert not LeagueBio()


class TestDetection:
    def test_skips_without_roster_data(self):
        """The lane stays dark rather than guessing at a nationality."""
        assert detect_lone_flag("2024-2025", 18, [_line("solo", 24)], None) is None
        assert detect_lone_flag("2024-2025", 18, [_line("solo", 24)], LeagueBio()) is None

    def test_fires_for_the_only_player_from_a_country(self):
        story = detect_lone_flag("2024-2025", 18, [_line("solo", 24), _line("a", 30)], _BIO)
        assert story.story_type is StoryType.LONE_FLAG
        assert story.facts["player_external_id"] == "solo"
        assert story.facts["nationality"] == "BENIN"
        assert story.facts["countrymen_in_season"] == 1

    def test_two_countrymen_is_not_a_story(self):
        assert detect_lone_flag("2024-2025", 18, [_line("c", 30)], _BIO) is None

    def test_a_quiet_night_is_not_a_story(self):
        """Being the only one from somewhere is not by itself news; the game
        has to be worth a card. Measured: the median such line is 8 points."""
        assert LONE_FLAG_MIN_POINTS == 15
        assert detect_lone_flag(
            "2024-2025", 18, [_line("solo", LONE_FLAG_MIN_POINTS - 1)], _BIO
        ) is None

    def test_the_headline_names_the_country(self):
        story = detect_lone_flag("2024-2025", 18, [_line("solo", 24)], _BIO)
        assert story.facts["section_label"] == "El único de BENIN"

    def test_runs_under_the_bio_scope(self):
        ctx = DetectionContext("2024-2025", 18, player_lines=(_line("solo", 24),), bio=_BIO)
        assert StoryType.LONE_FLAG in {s.story_type for s in run_detectors(ctx, {Scope.BIO})}
        # and self-skips when the context carries no roster
        bare = DetectionContext("2024-2025", 18, player_lines=(_line("solo", 24),))
        assert run_detectors(bare, {Scope.BIO}) == []


class TestCopy:
    def _copy(self):
        s = detect_lone_flag(
            "2024-2025", 18, [_line("solo", 24, name="CHABI YO, SOULEMANE")], _BIO
        )
        return s, generate_copy(
            {"story_type": s.story_type.value, "round_number": 18, "facts": s.facts}
        )

    def test_every_number_traces(self):
        s, c = self._copy()
        assert validate_copy(c.to_dict(), {**s.facts, "round_number": 18}).ok

    def test_claims_the_league_not_the_passport(self):
        """The FEB records ONE nationality per player, so the claim is about
        its roster. The copy must not overreach into anything stronger."""
        _, c = self._copy()
        assert "en toda la Segunda FEB" in c.caption
        assert "BENIN" in c.caption


class TestCard:
    def test_renders_with_the_longest_country_in_the_league(self):
        bio = LeagueBio({"solo": "SAN CRISTOBAL Y NIEVES"})
        s = detect_lone_flag("2024-2025", 18, [_line("solo", 21, name="WILLIAMS, KEITHRON")], bio)
        svg = render_template("player_of_round", {
            "story": {"facts": s.facts, "round_number": 18, "season_code": "2024-2025",
                      "story_type": s.story_type.value},
            "display": {"player": s.facts["player_name"], "team": "Basket Navarra"},
            "assets": {"player_initials": "KW"}, "copy": {}, "meta": {},
        })
        ET.fromstring(svg)
        assert "EL ÚNICO DE SAN CRISTOBAL Y NIEVES" in svg
        assert STORY_TO_TEMPLATE[StoryType.LONE_FLAG] == "player_of_round"

    def test_the_chip_does_not_repeat_the_headline(self):
        s = detect_lone_flag("2024-2025", 18, [_line("solo", 24)], _BIO)
        svg = render_template("player_of_round", {
            "story": {"facts": s.facts, "round_number": 18, "season_code": "2024-2025",
                      "story_type": s.story_type.value},
            "display": {"player": "X", "team": "T"},
            "assets": {"player_initials": "X"}, "copy": {}, "meta": {},
        })
        assert svg.count("ÚNICO") == 1


class TestOneCardPerSubject:
    """Measured on the live queue: round 26 gave FYNN SCHOTT three of its five
    cards (triple_double, player_of_round, season_high) — one night, one man,
    60% of the round's output. The per-type cap could not see it because each
    card was a different TYPE. Adding a fourth player detector made it worse,
    which is what forced the fix."""

    @staticmethod
    def _story(story_type, player, priority=80):
        from feb_score.domain.content.story import StoryEntities, StoryObject

        return StoryObject(
            story_type=story_type, season_code="2024-2025", round_number=26,
            entities=StoryEntities(player_external_id=player, team_external_id="t1"),
            facts={"player_external_id": player, "points": 21},
            source_refs={"player_stats": f"2afeb_score://x/{player}"},
            priority=priority,
        )

    def test_one_player_cannot_take_the_whole_round(self):
        from feb_score.domain.content.planner import plan
        from feb_score.domain.content.story import StoryStatus

        stories = [
            self._story(StoryType.TRIPLE_DOUBLE, "schott"),
            self._story(StoryType.PLAYER_OF_ROUND, "schott"),
            self._story(StoryType.SEASON_HIGH, "schott"),
            self._story(StoryType.DEFENSIVE_ANCHOR, "otro"),
            self._story(StoryType.PLAYMAKER, "tercero"),
        ]
        selected = [s for s in plan(stories, top_n=5)
                    if s.status is StoryStatus.SELECTED]
        subjects = [s.entities.player_external_id for s in selected]
        assert subjects.count("schott") == 1, subjects
        assert set(subjects) == {"schott", "otro", "tercero"}

    def test_the_strongest_story_about_him_is_the_one_that_survives(self):
        from feb_score.domain.content.planner import plan
        from feb_score.domain.content.story import StoryStatus

        stories = [
            self._story(StoryType.DOUBLE_DOUBLE, "schott"),
            self._story(StoryType.TRIPLE_DOUBLE, "schott"),
        ]
        selected = [s for s in plan(stories, top_n=5)
                    if s.status is StoryStatus.SELECTED]
        assert len(selected) == 1
        assert selected[0].story_type is StoryType.TRIPLE_DOUBLE

    def test_a_round_recap_has_no_subject_and_is_never_capped(self):
        from feb_score.domain.content.planner import _subject_of
        from feb_score.domain.content.story import StoryEntities, StoryObject

        recap = StoryObject(
            story_type=StoryType.ROUND_RECAP, season_code="2024-2025",
            round_number=26, entities=StoryEntities(), facts={}, source_refs={},
        )
        assert _subject_of(recap) is None

    def test_different_matches_are_different_subjects(self):
        from feb_score.domain.content.planner import _subject_of
        from feb_score.domain.content.story import StoryEntities, StoryObject

        def final(mid):
            return StoryObject(
                story_type=StoryType.MATCH_FINAL, season_code="2024-2025",
                round_number=26, entities=StoryEntities(match_external_id=mid),
                facts={}, source_refs={},
            )
        assert _subject_of(final("m1")) != _subject_of(final("m2"))
