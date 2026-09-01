"""Season-context detectors — season high, streaks, upset.

Deterministic reasoning over the SeasonContext DTO. Each detector must only
fire on real, demonstrable evidence and stay quiet otherwise.
"""

from __future__ import annotations

from datetime import datetime

from feb_score.domain.content.insights import MatchFactsInput, PlayerLineInput
from feb_score.domain.content.season_insights import (
    SeasonContext,
    detect_season_highs,
    detect_streaks,
    detect_upsets,
)
from feb_score.domain.content.story import StoryType


def _match(external_id="m1", home="tA", away="tB", hs=80, as_=70):
    return MatchFactsInput(
        external_id=external_id, season_code="2025-2026", round_number=12,
        home_team_external_id=home, away_team_external_id=away,
        home_team_name=f"Team {home}", away_team_name=f"Team {away}",
        home_score=hs, away_score=as_, scheduled_at=datetime(2026, 1, 24, 18, 0),
    )


def _player(pid="p1", team="tA", points=28, match="m1"):
    return PlayerLineInput(
        player_external_id=pid, player_name=f"Player {pid}", team_external_id=team,
        team_name=f"Team {team}", match_external_id=match, points=points,
        rebounds=6, assists=4,
    )


class TestSeasonHigh:
    def test_new_high_detected(self):
        # Current game (28) is a strict, unique season max over 4 prior games.
        ctx = SeasonContext(player_history={"p1": (12, 18, 20, 15, 28)})
        stories = detect_season_highs("2025-2026", 12, [_player(points=28)], ctx)
        assert len(stories) == 1
        assert stories[0].story_type is StoryType.SEASON_HIGH
        assert stories[0].facts["previous_best"] == 20

    def test_not_a_high_when_tied(self):
        ctx = SeasonContext(player_history={"p1": (28, 18, 20, 15, 28)})
        assert detect_season_highs("2025-2026", 12, [_player(points=28)], ctx) == []

    def test_not_a_high_below_threshold(self):
        ctx = SeasonContext(player_history={"p1": (5, 8, 10, 12, 18)})
        assert detect_season_highs("2025-2026", 12, [_player(points=18)], ctx) == []

    def test_needs_enough_prior_games(self):
        ctx = SeasonContext(player_history={"p1": (20, 28)})  # only 2 games
        assert detect_season_highs("2025-2026", 12, [_player(points=28)], ctx) == []


class TestStreaks:
    def test_win_streak_detected(self):
        ctx = SeasonContext(team_results={
            "tA": ((9, False), (10, True), (11, True), (12, True)),
        })
        stories = detect_streaks("2025-2026", 12, [_match(home="tA", away="tB")], ctx)
        wins = [s for s in stories if s.story_type is StoryType.WIN_STREAK]
        assert wins and wins[0].facts["streak_length"] == 3

    def test_loss_streak_detected(self):
        ctx = SeasonContext(team_results={
            "tB": ((9, True), (10, False), (11, False), (12, False)),
        })
        stories = detect_streaks("2025-2026", 12, [_match(home="tA", away="tB")], ctx)
        losses = [s for s in stories if s.story_type is StoryType.LOSS_STREAK]
        assert losses and losses[0].facts["streak_length"] == 3

    def test_short_streak_ignored(self):
        ctx = SeasonContext(team_results={"tA": ((11, False), (12, True))})
        assert detect_streaks("2025-2026", 12, [_match(home="tA")], ctx) == []


class TestUpset:
    def test_upset_detected(self):
        # tB (rank 12) beats tA (rank 3): gap 9 → upset. tB is the away winner.
        ctx = SeasonContext(team_rank={"tA": 3, "tB": 12})
        m = _match(home="tA", away="tB", hs=70, as_=80)  # away wins
        stories = detect_upsets("2025-2026", 12, [m], ctx)
        assert len(stories) == 1
        assert stories[0].story_type is StoryType.UPSET
        assert stories[0].facts["rank_gap"] == 9

    def test_no_upset_when_favorite_wins(self):
        ctx = SeasonContext(team_rank={"tA": 3, "tB": 12})
        m = _match(home="tA", away="tB", hs=80, as_=70)  # favorite (tA) wins
        assert detect_upsets("2025-2026", 12, [m], ctx) == []

    def test_no_upset_small_gap(self):
        ctx = SeasonContext(team_rank={"tA": 5, "tB": 8})
        m = _match(home="tA", away="tB", hs=70, as_=80)  # gap only 3
        assert detect_upsets("2025-2026", 12, [m], ctx) == []

    def test_no_rank_data_no_story(self):
        ctx = SeasonContext(team_rank={})
        m = _match(home="tA", away="tB", hs=70, as_=80)
        assert detect_upsets("2025-2026", 12, [m], ctx) == []


from feb_score.domain.content.season_insights import (  # noqa: E402
    GameLine, detect_player_streaks,
)


def _line(**kw):
    return GameLine(
        points=kw.get("points", 10), rebounds=kw.get("rebounds", 3),
        assists=kw.get("assists", 2), steals=kw.get("steals", 0),
        blocks=kw.get("blocks", 0),
    )


class TestPlayerStreaks:
    """Consecutive-game rachas ending in the current round. A gap resets the
    count — a season total is not a streak."""

    def test_scoring_streak_of_four_is_detected(self):
        log = tuple(_line(points=p) for p in [22, 25, 21, 30])  # last is current
        ctx = SeasonContext(player_game_log={"p1": log})
        stories = detect_player_streaks("2025-2026", 12, [_player(points=30)], ctx)
        types = {s.story_type for s in stories}
        assert StoryType.PLAYER_STREAK_SCORING in types
        s = next(s for s in stories if s.story_type == StoryType.PLAYER_STREAK_SCORING)
        assert s.facts["streak_length"] == 4
        assert s.facts["hero_value"] == 4

    def test_a_gap_resets_the_scoring_streak(self):
        # 20+ every other game: no run reaches the floor of 4 anywhere in the
        # log — the longest run is 1, so no story.
        log = tuple(_line(points=p) for p in [24, 8, 26, 9, 28])
        ctx = SeasonContext(player_game_log={"p1": log})
        assert detect_player_streaks("2025-2026", 12, [_player(points=28)], ctx) == []

    def test_a_peak_run_that_ended_is_still_a_story(self):
        """A season-long peak matters editorially even if the tail is broken.
        DESCUBRIR shows the peak; the pipeline agrees, with an is_active flag
        so future variants can frame it as LIVE or SEASON RECORD."""
        # Peak of 5 in the middle, then a broken tail.
        log = tuple(_line(points=p) for p in [22, 25, 21, 26, 30, 8, 12])
        ctx = SeasonContext(player_game_log={"p1": log})
        stories = detect_player_streaks("2025-2026", 12, [_player(points=12)], ctx)
        s = next(s for s in stories if s.story_type == StoryType.PLAYER_STREAK_SCORING)
        assert s.facts["streak_length"] == 5
        assert s.facts["is_active"] is False

    def test_a_run_still_active_is_flagged(self):
        log = tuple(_line(points=p) for p in [22, 25, 21, 26, 30])
        ctx = SeasonContext(player_game_log={"p1": log})
        stories = detect_player_streaks("2025-2026", 12, [_player(points=30)], ctx)
        s = next(s for s in stories if s.story_type == StoryType.PLAYER_STREAK_SCORING)
        assert s.facts["is_active"] is True

    def test_streak_below_the_floor_is_ignored(self):
        log = tuple(_line(points=p) for p in [22, 25, 21])   # 3, floor is 4
        ctx = SeasonContext(player_game_log={"p1": log})
        assert detect_player_streaks("2025-2026", 12, [_player(points=21)], ctx) == []

    def test_only_the_player_who_played_this_round_gets_a_story(self):
        """The streak has to be LIVE. A player with a great log who did not
        play in the current round does not deserve a raced-in card."""
        log = tuple(_line(points=p) for p in [22, 25, 21, 30])
        ctx = SeasonContext(player_game_log={"absent": log})
        # No player in this round: absent's streak does not fire.
        assert detect_player_streaks("2025-2026", 12, [], ctx) == []

    def test_double_double_streak_of_three(self):
        log = (_line(points=12, rebounds=11),
               _line(points=10, rebounds=10, assists=2),
               _line(points=8, rebounds=4, assists=10))   # 8/4/10 -> only 1 stat >=10
        ctx = SeasonContext(player_game_log={"p1": log})
        stories = detect_player_streaks("2025-2026", 12, [_player(points=8)], ctx)
        assert stories == []                                # 8/4/10 broke the streak
        # Now three consecutive DDs ending at the current game
        log = (_line(points=12, rebounds=11),
               _line(points=10, rebounds=10, assists=2),
               _line(points=11, rebounds=10, assists=1))
        ctx = SeasonContext(player_game_log={"p1": log})
        stories = detect_player_streaks("2025-2026", 12, [_player(points=11)], ctx)
        types = {s.story_type for s in stories}
        assert StoryType.PLAYER_STREAK_DD in types
        s = next(s for s in stories if s.story_type == StoryType.PLAYER_STREAK_DD)
        assert s.facts["streak_length"] == 3

    def test_facts_carry_the_current_game_line_as_supporting_stats(self):
        """The supporting line on the card must describe the RECENT game (what
        keeps the streak alive), not the streak's average."""
        log = tuple(_line(points=p) for p in [22, 25, 21, 30])
        ctx = SeasonContext(player_game_log={"p1": log})
        s = detect_player_streaks("2025-2026", 12, [_player(points=30)], ctx)[0]
        secondary = {lab: v for v, lab in s.facts["secondary"]}
        assert secondary["PTS"] == 30
