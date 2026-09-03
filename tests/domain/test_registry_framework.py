"""Detector registry framework — the pattern-detection engine.

Proves the framework contract: existing detectors are registered by scope, the
runner filters by scope and collects, a new detector is pluggable in one call,
the season aggregate folds correctly, and a season-scope detector flows all the
way to a rendered card.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from feb_score.domain.content import registry
from feb_score.domain.content.copy import generate_copy
from feb_score.domain.content.insights import PlayerLineInput
from feb_score.domain.content.registry import (
    DetectionContext,
    Scope,
    register,
    registered,
    run_detectors,
)
from feb_score.domain.content.season_aggregate import (
    build_season_aggregate,
    detect_season_assist_leader,
    detect_season_rebounding_leader,
    detect_season_scoring_leader,
)
from feb_score.domain.content.story import STORY_TO_TEMPLATE, StoryType
from feb_score.domain.content.validation import validate_copy
from feb_score.infrastructure.rendering.component_templates import render_template


def _line(pid, pts, reb=4, ast=3, name=None):
    return PlayerLineInput(pid, name or pid.upper(), "t", "Team", "m", pts, reb, ast)


class TestRegistry:
    def test_existing_detectors_registered_by_scope(self):
        round_names = {s.name for s in registered(Scope.ROUND)}
        assert {"match_final", "player_of_round", "stat_leaderboard", "iron_man"} <= round_names
        season_names = {s.name for s in registered(Scope.SEASON)}
        assert {"season_highs", "team_streaks", "upsets", "season_scoring_leader",
                "season_rebounding_leader", "season_assist_leader"} <= season_names

    def test_run_filters_by_scope(self):
        ctx = DetectionContext(
            "2025-2026", 5, player_lines=(_line("a", 20), _line("b", 15), _line("c", 10))
        )
        assert run_detectors(ctx, {Scope.ROUND})           # round detectors fire
        assert run_detectors(ctx, {Scope.SEASON}) == []     # no season data → nothing

    def test_register_is_pluggable(self):
        snapshot = list(registry._REGISTRY)
        try:
            @register("dummy_test_detector", Scope.ROUND)
            def _dummy(ctx):
                return []
            assert any(s.name == "dummy_test_detector" for s in registered(Scope.ROUND))
        finally:
            registry._REGISTRY[:] = snapshot  # never pollute the global registry
        assert not any(s.name == "dummy_test_detector" for s in registered())


class TestSeasonAggregate:
    def test_folds_rounds(self):
        r1 = [_line("a", 20, name="A. Uno"), _line("b", 10)]
        r2 = [_line("a", 30, name="A. Uno")]
        agg = build_season_aggregate("2025-2026", [r1, r2])
        a = next(p for p in agg.players if p.player_external_id == "a")
        assert a.games == 2 and a.points == 50 and a.player_name == "A. Uno"
        assert a.ppg == 25.0

    def test_scoring_leader_skips_without_aggregate(self):
        assert detect_season_scoring_leader("2025-2026", 5, None) == []

    def test_scoring_leader_fires_with_enough_games(self):
        agg = build_season_aggregate(
            "2025-2026", [[_line("a", 30, name="A. Uno"), _line("b", 10)]] * 3
        )
        stories = detect_season_scoring_leader("2025-2026", 5, agg)
        assert stories and stories[0].story_type is StoryType.TOP_SCORER
        assert stories[0].facts["points"] == 90 and stories[0].facts["games_played"] == 3

    def test_rebounding_leader_fires_and_renders(self):
        agg = build_season_aggregate(
            "2025-2026", [[_line("a", 10, reb=14, name="R. Grande"), _line("b", 30, reb=3)]] * 3
        )
        stories = detect_season_rebounding_leader("2025-2026", 5, agg)
        assert stories and stories[0].story_type is StoryType.TOP_REBOUNDER
        s = stories[0]
        assert s.facts["rebounds"] == 42 and s.facts["hero_label"] == "REB TOTALES"
        copy = generate_copy(
            {"story_type": s.story_type.value, "round_number": 5, "facts": s.facts}
        )
        assert validate_copy(copy.to_dict(), {**s.facts, "round_number": 5}).ok

    def test_assist_leader_fires(self):
        agg = build_season_aggregate(
            "2025-2026", [[_line("a", 8, ast=12, name="P. Guía"), _line("b", 30, ast=2)]] * 3
        )
        stories = detect_season_assist_leader("2025-2026", 5, agg)
        assert stories and stories[0].story_type is StoryType.TOP_ASSIST_PROVIDER
        s = stories[0]
        assert s.facts["assists"] == 36 and s.facts["hero_label"] == "AST TOTALES"
        copy = generate_copy(
            {"story_type": s.story_type.value, "round_number": 5, "facts": s.facts}
        )
        assert validate_copy(copy.to_dict(), {**s.facts, "round_number": 5}).ok


class TestEndToEnd:
    def test_season_leader_flows_to_render(self):
        agg = build_season_aggregate(
            "2025-2026", [[_line("a", 30, name="C. Sáez"), _line("b", 10)]] * 4
        )
        stories = run_detectors(DetectionContext("2025-2026", 5, season=agg), {Scope.SEASON})
        top = [s for s in stories if s.story_type is StoryType.TOP_SCORER]
        assert top
        s = top[0]
        # copy validates (no invented numbers)
        copy = generate_copy(
            {"story_type": s.story_type.value, "round_number": s.round_number, "facts": s.facts}
        )
        vf = {**s.facts, "round_number": s.round_number}
        assert validate_copy(copy.to_dict(), vf).ok
        # renders through the mapped template
        assert STORY_TO_TEMPLATE[s.story_type] == "player_of_round"
        data = {
            "story": {"facts": s.facts, "round_number": 5, "season_code": "2025-2026"},
            "display": {"player": "C. Sáez", "team": "Alicante"},
            "assets": {"player_initials": "CS"}, "copy": {}, "meta": {},
        }
        ET.fromstring(render_template("player_of_round", data))


# --- FEB Rating on season cards (regression) --------------------------------

def test_season_line_rating_stays_none_when_minutes_or_shooting_are_missing():
    """The mark needs minutes AND shooting efficiency to stay comparable with a
    boxscore rating. When either is absent the line refuses to grade itself —
    "unknown" is not the same as "average". This is the safety property; the
    happy path is covered by the next test."""
    from feb_score.domain.content.season_aggregate import PlayerSeasonLine

    # No minutes, no shooting → None
    assert PlayerSeasonLine(
        player_external_id="p1", games=26, points=450, rebounds=112,
        assists=72, steals=23, blocks=1, turnovers=77,
    ).rating is None

    # Minutes but no shooting → still None (efficiency term missing)
    assert PlayerSeasonLine(
        player_external_id="p1", games=26, points=450, rebounds=112,
        assists=72, minutes=650.0,
    ).rating is None

    # Zero games → None
    assert PlayerSeasonLine("p2", games=0, points=0, rebounds=0, assists=0).rating is None


def test_season_line_rating_computes_over_the_average_game_when_data_is_there():
    """Once minutes and shooting are aggregated, the rating grades the AVERAGE
    game (not the totals) so a season card sits on the same 0..10 scale as a
    boxscore card."""
    from feb_score.domain.content.season_aggregate import PlayerSeasonLine

    line = PlayerSeasonLine(
        player_external_id="p1", games=20, points=400, rebounds=100,
        assists=60, steals=20, blocks=10, turnovers=40,
        minutes=600.0, field_goals_made=140, field_goals_attempted=280,
    )
    assert line.minutes_per_game == 30.0
    assert line.rating is not None
    assert 0.0 <= line.rating <= 10.0


def test_season_leader_story_carries_a_rating_once_the_aggregate_is_complete():
    from feb_score.domain.content.season_aggregate import (
        PlayerSeasonLine, SeasonAggregate, detect_season_scoring_leader,
    )

    agg = SeasonAggregate("2024-2025", (PlayerSeasonLine(
        player_external_id="p1", games=26, points=450, rebounds=112,
        assists=72, steals=23, blocks=1, turnovers=77, player_name="X",
        minutes=780.0, field_goals_made=170, field_goals_attempted=330),))
    story = detect_season_scoring_leader("2024-2025", 26, agg)[0]
    assert story.facts["season_total"] == 450
    assert story.facts["rating"] is not None
    assert 0.0 <= story.facts["rating"] <= 10.0


def test_season_fold_accumulates_defensive_stats():
    from feb_score.domain.content.insights import PlayerLineInput
    from feb_score.domain.content.season_aggregate import build_season_aggregate

    def line(**kw):
        base = dict(player_external_id="p1", team_external_id="t1", points=10,
                    rebounds=4, assists=2, steals=1, blocks=1, turnovers=2,
                    minutes=20.0, match_external_id="m",
                    player_name="X", team_name="T")
        base.update(kw)
        return PlayerLineInput(**base)

    agg = build_season_aggregate("2024-2025", [[line()], [line(steals=3, blocks=0, turnovers=1)]])
    p = agg.players[0]
    assert (p.steals, p.blocks, p.turnovers) == (4, 1, 3)


def test_season_fold_sums_minutes_and_shooting_when_every_game_carries_them():
    from feb_score.domain.content.insights import PlayerLineInput
    from feb_score.domain.content.season_aggregate import build_season_aggregate

    def line(**kw):
        base = dict(player_external_id="p1", team_external_id="t1", points=20,
                    rebounds=5, assists=3, steals=1, blocks=0, turnovers=2,
                    minutes=28.0, match_external_id="m",
                    field_goals_made=7, field_goals_attempted=15,
                    player_name="X", team_name="T")
        base.update(kw)
        return PlayerLineInput(**base)

    agg = build_season_aggregate("2024-2025", [[line()], [line(minutes=32.0,
        field_goals_made=8, field_goals_attempted=14)]])
    p = agg.players[0]
    assert p.minutes == 60.0
    assert p.field_goals_made == 15
    assert p.field_goals_attempted == 29
    assert p.minutes_per_game == 30.0
    assert p.rating is not None  # complete data → rating computable


def test_season_fold_leaves_shooting_none_when_any_game_lacks_it():
    """If one game came in without shooting data, we cannot honestly report a
    season shooting rate — so the aggregate stays None rather than lie by
    treating the gap as zero attempts."""
    from feb_score.domain.content.insights import PlayerLineInput
    from feb_score.domain.content.season_aggregate import build_season_aggregate

    complete = PlayerLineInput(
        player_external_id="p1", team_external_id="t1", points=20, rebounds=5,
        assists=3, steals=1, blocks=0, turnovers=2, minutes=28.0,
        match_external_id="m", player_name="X", team_name="T",
        field_goals_made=7, field_goals_attempted=15,
    )
    incomplete = PlayerLineInput(
        player_external_id="p1", team_external_id="t1", points=18, rebounds=6,
        assists=2, steals=0, blocks=1, turnovers=1, minutes=30.0,
        match_external_id="m2", player_name="X", team_name="T",
        # shooting deliberately absent
    )
    agg = build_season_aggregate("2024-2025", [[complete], [incomplete]])
    p = agg.players[0]
    assert p.minutes == 58.0                    # minutes still sum
    assert p.field_goals_made is None
    assert p.field_goals_attempted is None
    assert p.rating is None                     # no shooting → no rating


def test_season_best_five_ranks_by_rating_and_self_skips_without_feb_map():
    """Top 5 of the season by FEB Rating. Needs feb_by_player populated (the
    adapter fills it from per-game blobs); without it the detector must
    self-skip rather than crown five zeros."""
    from feb_score.domain.content.season_aggregate import (
        PlayerSeasonLine, SeasonAggregate, detect_season_best_five,
    )
    from feb_score.domain.content.story import StoryType

    def _line(pid, pts, games=10):
        return PlayerSeasonLine(
            player_external_id=pid, games=games, points=pts, rebounds=5*games,
            assists=3*games, player_name=pid.upper(), team_external_id="t1",
            team_name="Team A",
        )
    players = tuple(_line(f"p{i}", 20+i) for i in range(1, 7))
    # No feb_by_player → self-skip.
    assert detect_season_best_five("2024-2025", 20, SeasonAggregate(
        "2024-2025", players)) == []

    # With a feb map, the ranking picks the top 5.
    feb = {"p1": 6.5, "p2": 7.0, "p3": 7.8, "p4": 6.0, "p5": 8.5, "p6": 8.1}
    agg = SeasonAggregate("2024-2025", players, feb_by_player=feb)
    stories = detect_season_best_five("2024-2025", 20, agg)
    assert len(stories) == 1
    st = stories[0]
    assert st.story_type is StoryType.BEST_FIVE_SEASON
    picked = [row["player_external_id"] for row in st.facts["lineup"]]
    assert picked == ["p5", "p6", "p3", "p2", "p1"]  # by FEB desc
    assert st.facts["lineup"][0]["rating"] == 8.5


def test_season_best_five_requires_minimum_games_for_a_real_note():
    from feb_score.domain.content.season_aggregate import (
        PlayerSeasonLine, SeasonAggregate, detect_season_best_five,
        SEASON_QUINTET_MIN_GAMES,
    )

    # 5 players over the floor, 1 cameo with a 10.0 note.
    real = tuple(PlayerSeasonLine(
        player_external_id=f"p{i}", games=SEASON_QUINTET_MIN_GAMES, points=100,
        rebounds=50, assists=30, player_name=f"P{i}", team_external_id="t",
        team_name="Team") for i in range(1, 6))
    cameo = PlayerSeasonLine(
        player_external_id="cameo", games=2, points=40, rebounds=10, assists=5,
        player_name="CAMEO", team_external_id="t", team_name="Team")
    feb = {**{f"p{i}": 7.0 + i * 0.1 for i in range(1, 6)}, "cameo": 10.0}
    agg = SeasonAggregate("2024-2025", real + (cameo,), feb_by_player=feb)
    story = detect_season_best_five("2024-2025", 20, agg)[0]
    picked = [row["player_external_id"] for row in story.facts["lineup"]]
    assert "cameo" not in picked  # min-games floor kept the cameo out


def test_season_best_five_ideal_picks_one_per_position_and_needs_all_five():
    from feb_score.domain.content.season_aggregate import (
        PlayerSeasonLine, SeasonAggregate, detect_season_best_five_ideal,
        SEASON_QUINTET_MIN_GAMES,
    )
    from feb_score.domain.content.bio import POSITIONS

    class _Bio:
        def __init__(self, m): self._m = m
        def position(self, pid): return self._m.get(pid)

    players = tuple(PlayerSeasonLine(
        player_external_id=f"p{i}", games=SEASON_QUINTET_MIN_GAMES, points=100,
        rebounds=50, assists=30, player_name=f"P{i}", team_external_id="t",
        team_name="Team") for i in range(1, 6))
    feb = {f"p{i}": 7.5 + i * 0.1 for i in range(1, 6)}
    # One player per position → a full ideal five.
    positions = dict(zip((f"p{i}" for i in range(1, 6)), POSITIONS))
    agg = SeasonAggregate("2024-2025", players, feb_by_player=feb)
    story = detect_season_best_five_ideal("2024-2025", 20, agg, _Bio(positions))[0]
    assert [row["position"] for row in story.facts["lineup"]] == list(POSITIONS)

    # Drop the pivot's position → hole at a position → no card.
    del positions[next(k for k, v in positions.items() if v == POSITIONS[0])]
    assert detect_season_best_five_ideal("2024-2025", 20, agg, _Bio(positions)) == []


def test_game_line_rating_computes_when_the_data_is_complete_and_none_otherwise():
    from feb_score.domain.content.season_insights import GameLine

    # The base fields alone (rachas detectors) don't earn a rating.
    assert GameLine(points=20, rebounds=5, assists=3).rating is None
    # Minutes without shooting still not enough.
    assert GameLine(points=20, minutes=28.0).rating is None
    # Full data → rating on the 0..10 scale.
    line = GameLine(points=22, rebounds=6, assists=4, steals=1, blocks=1,
                    turnovers=2, minutes=30.0,
                    field_goals_made=8, field_goals_attempted=15)
    assert line.rating is not None
    assert 0.0 <= line.rating <= 10.0


def test_every_player_card_story_carries_the_rating():
    """Regression guard. The FEB Rating went missing on season_high because that
    detector built its facts by hand instead of using the canonical builder — the
    third time that duplication cost us the mark. Any story mapped to the player
    card must carry a rating (or None when the line genuinely can't be graded),
    never omit the key."""
    from feb_score.domain.content.insights import PlayerLineInput, player_facts
    from feb_score.domain.content.season_insights import SeasonContext, detect_season_highs
    from feb_score.domain.content.story import STORY_TO_TEMPLATE, StoryType

    line = PlayerLineInput(
        "p1", "P. Uno", "t1", "Team", "m1", points=32, rebounds=6, assists=3,
        steals=1, blocks=0, turnovers=2, minutes=30.0,
        field_goals_made=12, field_goals_attempted=18, three_points_made=3,
        three_points_attempted=6, free_throws_made=5, free_throws_attempted=6,
        fouls=2, fouls_received=4,
    )
    assert player_facts(line)["rating"] is not None

    ctx = SeasonContext(player_history={"p1": (10, 12, 15, 11, 32)})  # needs a real baseline
    stories = detect_season_highs("2024-2025", 25, [line], ctx)
    assert stories, "expected a season high"
    for s in stories:
        if STORY_TO_TEMPLATE.get(s.story_type) == "player_of_round":
            assert "rating" in s.facts, f"{s.story_type} lost the rating"
            assert s.facts["rating"] is not None


def test_every_player_card_type_says_what_it_is():
    """Regression: all four of double/triple double, season high and player of
    the round fell through to the template default, so a triple-double card
    announced itself as 'Jugador de la jornada' with an MVP badge. Every type
    sharing the player card must declare its own headline."""
    from feb_score.domain.content.story import STORY_TO_TEMPLATE, labels_for

    sharing = [t for t, tpl in STORY_TO_TEMPLATE.items() if tpl == "player_of_round"]
    assert len(sharing) > 5
    seen = {}
    for t in sharing:
        lab = labels_for(t)
        assert lab["section"], f"{t.value} has no headline of its own"
        assert lab["badge"], f"{t.value} has no badge of its own"
        assert lab["section"] not in seen, (
            f"{t.value} reuses the headline of {seen.get(lab['section'])}")
        seen[lab["section"]] = t.value


def test_the_card_renders_its_own_headline():
    import re

    from feb_score.infrastructure.rendering.component_templates import render_template

    def head(story_type):
        data = {"story": {"facts": {"player_name": "X", "points": 21, "rebounds": 13,
                                    "assists": 10, "rating": 9.0},
                          "round_number": 24, "season_code": "2024-2025",
                          "story_type": story_type},
                "display": {"player": "X", "team": "T"},
                "assets": {"player_initials": "X"}, "copy": {}, "meta": {}}
        return re.findall(r'>([A-ZÁÉÍÓÚÑ\- ]{5,45})<', render_template("player_of_round", data))[0]

    assert head("triple_double") == "TRIPLE-DOBLE"
    assert head("season_high") == "MÁXIMO PERSONAL DE LA TEMPORADA"
    assert head("player_of_round") == "JUGADOR DE LA JORNADA"


def test_the_portrait_chip_does_not_echo_the_headline():
    """Giving every type its own headline made several cards say the same thing
    twice — a TRIPLE-DOBLE headline over a TRIPLE-DOBLE chip. The chip is there
    to ADD a qualifier, so it is dropped when it only repeats, abbreviations
    included."""
    from feb_score.domain.content.story import badge_echoes_headline

    assert badge_echoes_headline("Triple-doble", "TRIPLE-DOBLE")
    assert badge_echoes_headline("Máximo personal de la temporada", "MÁXIMO")
    assert badge_echoes_headline("Máximo anotador de la temporada", "MÁX. ANOTADOR")
    assert badge_echoes_headline("El director de juego", "DIRECTOR")

    assert not badge_echoes_headline("Jugador de la jornada", "MVP")
    assert not badge_echoes_headline("El tirador de la jornada", "SNIPER")
    assert not badge_echoes_headline("Noche perfecta", "SIN FALLO")
    assert not badge_echoes_headline("El más trabajador", "MARATÓN")
    assert not badge_echoes_headline("Jugador de la jornada", "")


def test_the_rendered_card_shows_each_label_once():
    from feb_score.infrastructure.rendering.component_templates import render_template

    def card(story_type):
        data = {"story": {"facts": {"player_name": "X", "points": 21, "rebounds": 13,
                                    "assists": 10, "rating": 9.0},
                          "round_number": 24, "season_code": "2024-2025",
                          "story_type": story_type},
                "display": {"player": "X", "team": "T"},
                "assets": {"player_initials": "X"}, "copy": {}, "meta": {}}
        return render_template("player_of_round", data)

    assert card("triple_double").count("TRIPLE-DOBLE") == 1   # headline only
    assert card("player_of_round").count("MVP") == 1          # the chip survives
