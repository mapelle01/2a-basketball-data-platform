"""Season-context insight detectors.

Unlike the round detectors in ``insights.py`` (which need only the current
round), these compare the round against the season so far: a player's prior
best, a team's streak, the classification table. They stay pure — the
``SeasonContext`` DTO carries the raw season data (assembled by the adapter);
the detectors do the reasoning here in the domain.

Detectors:
  - detect_season_highs  (a player's new season-best scoring game)
  - detect_streaks       (a team on a 3+ win or loss run)
  - detect_upsets        (a much lower-ranked team beats a much higher one)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .insights import MatchFactsInput, PlayerLineInput
from .story import StoryEntities, StoryObject, StoryType


# Editorial thresholds — one obvious place to tune per season.
SEASON_HIGH_MIN_POINTS = 20     # below this a "career night" isn't a story
SEASON_HIGH_MIN_PRIOR_GAMES = 3  # need a real baseline to call it a high
STREAK_MIN_LENGTH = 3
UPSET_MIN_RANK_GAP = 6           # winner must be 6+ places below the loser


@dataclass(frozen=True)
class SeasonContext:
    """Raw season data needed by the season detectors. The adapter fills it;
    the detectors reason over it.

    * ``player_history``: player_external_id -> (points, ...) for EVERY game the
      player has this season, INCLUDING the current round's game (PlayerStats
      carries no match id, so the current game is identified as the unique
      season maximum, not excluded by id).
    * ``team_results``: team_external_id -> ((round_number, won), ...) ordered by
      round ascending (won is True for a win, False for a loss).
    * ``team_rank``: team_external_id -> classification rank (1 = top).
    """

    player_history: Dict[str, Tuple[int, ...]] = field(default_factory=dict)
    team_results: Dict[str, Tuple[Tuple[int, bool], ...]] = field(default_factory=dict)
    team_rank: Dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Season high
# ---------------------------------------------------------------------------


def detect_season_highs(
    season_code: str,
    round_number: int,
    player_lines: Sequence[PlayerLineInput],
    context: SeasonContext,
) -> List[StoryObject]:
    stories: List[StoryObject] = []
    for p in player_lines:
        if p.points < SEASON_HIGH_MIN_POINTS:
            continue
        history = context.player_history.get(p.player_external_id)
        # Need a baseline: the current game plus at least N prior games.
        if not history or len(history) < SEASON_HIGH_MIN_PRIOR_GAMES + 1:
            continue
        season_max = max(history)
        # Strict new high: the round's game IS the season max AND that max is
        # unique (a tie is not a *new* high).
        if p.points != season_max or history.count(season_max) != 1:
            continue
        previous_best = max(v for v in history if v != season_max)

        stories.append(StoryObject(
            story_type=StoryType.SEASON_HIGH,
            season_code=season_code,
            round_number=round_number,
            entities=StoryEntities(
                player_external_id=p.player_external_id,
                team_external_id=p.team_external_id,
                match_external_id=p.match_external_id,
            ),
            facts={
                "player_external_id": p.player_external_id,
                "player_name": p.player_name,
                "team_external_id": p.team_external_id,
                "team_name": p.team_name,
                "points": p.points,
                "rebounds": p.rebounds,
                "assists": p.assists,
                "impact_score": round(p.impact_score, 1),
                "previous_best": previous_best,
                "games_played": len(history),
                "match_external_id": p.match_external_id,
            },
            source_refs={
                "player_season_stats": (
                    f"2afeb_score://season_player_stats/{season_code}/"
                    f"{p.player_external_id}"
                ),
            },
        ))
    return stories


# ---------------------------------------------------------------------------
# Streaks
# ---------------------------------------------------------------------------


def detect_streaks(
    season_code: str,
    round_number: int,
    matches: Sequence[MatchFactsInput],
    context: SeasonContext,
) -> List[StoryObject]:
    stories: List[StoryObject] = []
    seen: set = set()
    for m in matches:
        for team_id in (m.home_team_external_id, m.away_team_external_id):
            if team_id in seen:
                continue
            seen.add(team_id)
            results = context.team_results.get(team_id)
            if not results:
                continue
            kind, length = _current_streak(results)
            if length < STREAK_MIN_LENGTH:
                continue
            story_type = StoryType.WIN_STREAK if kind == "win" else StoryType.LOSS_STREAK
            team_name = m.home_team_name if team_id == m.home_team_external_id else m.away_team_name
            stories.append(StoryObject(
                story_type=story_type,
                season_code=season_code,
                round_number=round_number,
                entities=StoryEntities(team_external_id=team_id),
                facts={
                    "team_external_id": team_id,
                    "team_name": team_name,
                    "streak_kind": kind,
                    "streak_length": length,
                },
                source_refs={
                    "team_rounds": (
                        f"2afeb_score://season_team_rounds/{season_code}/{team_id}"
                    ),
                },
            ))
    return stories


def _current_streak(results: Tuple[Tuple[int, bool], ...]) -> Tuple[str, int]:
    """Length and kind of the streak ending at the most recent round."""
    ordered = sorted(results, key=lambda r: r[0])
    if not ordered:
        return ("none", 0)
    last_won = ordered[-1][1]
    length = 0
    for _round, won in reversed(ordered):
        if won == last_won:
            length += 1
        else:
            break
    return ("win" if last_won else "loss", length)


# ---------------------------------------------------------------------------
# Upset
# ---------------------------------------------------------------------------


def detect_upsets(
    season_code: str,
    round_number: int,
    matches: Sequence[MatchFactsInput],
    context: SeasonContext,
) -> List[StoryObject]:
    stories: List[StoryObject] = []
    for m in matches:
        winner = m.winner_id
        loser = m.loser_id
        wr = context.team_rank.get(winner)
        lr = context.team_rank.get(loser)
        if wr is None or lr is None:
            continue
        gap = wr - lr  # positive when the winner is ranked BELOW the loser
        if gap < UPSET_MIN_RANK_GAP:
            continue

        winner_name = m.home_team_name if winner == m.home_team_external_id else m.away_team_name
        loser_name = m.home_team_name if loser == m.home_team_external_id else m.away_team_name
        stories.append(StoryObject(
            story_type=StoryType.UPSET,
            season_code=season_code,
            round_number=round_number,
            entities=StoryEntities(
                match_external_id=m.external_id,
                home_team_external_id=m.home_team_external_id,
                away_team_external_id=m.away_team_external_id,
            ),
            facts={
                "home_team_external_id": m.home_team_external_id,
                "away_team_external_id": m.away_team_external_id,
                "home_team_name": m.home_team_name,
                "away_team_name": m.away_team_name,
                "home_score": m.home_score,
                "away_score": m.away_score,
                "margin": abs(m.home_score - m.away_score),
                "winner_name": winner_name,
                "loser_name": loser_name,
                "winner_rank": wr,
                "loser_rank": lr,
                "rank_gap": gap,
            },
            source_refs={
                "match": f"2afeb_score://matches/{m.external_id}",
                "classification": f"2afeb_score://season_classification/{season_code}",
            },
        ))
    return stories


def detect_all_season(
    season_code: str,
    round_number: int,
    matches: Sequence[MatchFactsInput],
    player_lines: Sequence[PlayerLineInput],
    context: Optional[SeasonContext],
) -> List[StoryObject]:
    """Run the SEASON-scope detectors that depend on ``SeasonContext``. Delegates
    to the detector registry; kept as a convenience entry point."""
    if context is None:
        return []
    from .registry import DetectionContext, Scope, run_detectors  # lazy: avoid import cycle

    ctx = DetectionContext(
        season_code=season_code, round_number=round_number,
        matches=tuple(matches), player_lines=tuple(player_lines), season_context=context,
    )
    # SEASON scope minus the aggregate-only detectors (this entry point carries a
    # SeasonContext, not a SeasonAggregate — those self-skip anyway).
    return run_detectors(ctx, {Scope.SEASON})
