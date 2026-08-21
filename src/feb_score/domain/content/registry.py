"""Detector registry — the pattern-detection framework.

Every detector is a small pure function that declares its SCOPE (the data it
needs) and returns 0..N StoryObjects. The runner executes every registered
detector whose scope is enabled and collects the stories; the Planner scores and
selects downstream. Adding a new pattern = writing a detector and registering it
here — no caller changes, nothing else to touch.

A detector NEVER inspects whether its data exists at the runner level: it
self-skips (returns nothing) when its inputs are absent. So the runner stays
dumb and the framework scales to season/all-time/bio scopes by just adding
detectors and filling the matching field on ``DetectionContext``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Iterable, List, Optional, Sequence

from . import insights as _ins
from . import season_insights as _sea
from . import season_aggregate as _agg
from .insights import MatchFactsInput, PlayerLineInput
from .season_aggregate import SeasonAggregate
from .season_insights import SeasonContext
from .story import StoryObject


class Scope(str, Enum):
    ROUND = "round"      # needs only the current round's boxscore
    SEASON = "season"    # needs season-to-date context / aggregate
    # Future: ALLTIME (multi-season history), BIO (roster attributes).


@dataclass(frozen=True)
class DetectionContext:
    """Everything a detector might read. Optional fields stay None until their
    data source is wired; detectors that need them self-skip meanwhile."""

    season_code: str
    round_number: int
    matches: Sequence[MatchFactsInput] = ()
    player_lines: Sequence[PlayerLineInput] = ()
    season_context: Optional[SeasonContext] = None      # prior-best / streaks / rank
    season: Optional[SeasonAggregate] = None            # season-to-date totals


Detector = Callable[[DetectionContext], Iterable[StoryObject]]


@dataclass(frozen=True)
class DetectorSpec:
    name: str
    scope: Scope
    fn: Detector


_REGISTRY: List[DetectorSpec] = []


def register(name: str, scope: Scope) -> Callable[[Detector], Detector]:
    """Decorator: add a detector to the registry under a scope."""
    def deco(fn: Detector) -> Detector:
        _REGISTRY.append(DetectorSpec(name=name, scope=scope, fn=fn))
        return fn
    return deco


def registered(scope: Optional[Scope] = None) -> Sequence[DetectorSpec]:
    return tuple(s for s in _REGISTRY if scope is None or s.scope is scope)


def run_detectors(
    ctx: DetectionContext, scopes: Optional[Iterable[Scope]] = None,
) -> List[StoryObject]:
    """Run every registered detector whose scope is enabled, in registration
    order, and collect the stories. Detectors self-skip when their data is
    absent, so this stays a dumb collector."""
    allowed = set(scopes) if scopes is not None else set(Scope)
    stories: List[StoryObject] = []
    for spec in _REGISTRY:
        if spec.scope not in allowed:
            continue
        stories.extend(spec.fn(ctx) or ())
    return stories


# ---------------------------------------------------------------------------
# Register the existing detectors as thin adapters (order preserved so the
# legacy ``detect_all_*`` entry points return exactly what they always did).
# ---------------------------------------------------------------------------

# --- ROUND scope ---
register("match_final", Scope.ROUND)(
    lambda ctx: [_ins.detect_match_final(m) for m in ctx.matches]
)
register("player_of_round", Scope.ROUND)(
    lambda ctx: _one(_ins.detect_player_of_round(ctx.season_code, ctx.round_number, ctx.player_lines))
)
register("round_recap", Scope.ROUND)(
    lambda ctx: _one(_ins.detect_round_recap(ctx.season_code, ctx.round_number, ctx.matches, ctx.player_lines))
)
register("biggest_win", Scope.ROUND)(
    lambda ctx: _one(_ins.detect_biggest_win(ctx.season_code, ctx.round_number, ctx.matches))
)
register("notable_performances", Scope.ROUND)(
    lambda ctx: _ins.detect_notable_performances(ctx.season_code, ctx.round_number, ctx.player_lines)
)
register("stat_leaderboard", Scope.ROUND)(
    lambda ctx: _one(_ins.detect_stat_leaderboard(ctx.season_code, ctx.round_number, ctx.player_lines))
)
register("iron_man", Scope.ROUND)(
    lambda ctx: _one(_ins.detect_iron_man(ctx.season_code, ctx.round_number, ctx.player_lines))
)
register("playmaker", Scope.ROUND)(
    lambda ctx: _one(_ins.detect_playmaker(ctx.season_code, ctx.round_number, ctx.player_lines))
)
register("sharpshooter", Scope.ROUND)(
    lambda ctx: _one(_ins.detect_sharpshooter(ctx.season_code, ctx.round_number, ctx.player_lines))
)
register("perfect_night", Scope.ROUND)(
    lambda ctx: _one(_ins.detect_perfect_night(ctx.season_code, ctx.round_number, ctx.player_lines))
)

# --- SEASON scope --- (self-skip when their context/aggregate is None)
register("season_highs", Scope.SEASON)(
    lambda ctx: _sea.detect_season_highs(ctx.season_code, ctx.round_number, ctx.player_lines, ctx.season_context)
    if ctx.season_context is not None else []
)
register("team_streaks", Scope.SEASON)(
    lambda ctx: _sea.detect_streaks(ctx.season_code, ctx.round_number, ctx.matches, ctx.season_context)
    if ctx.season_context is not None else []
)
register("upsets", Scope.SEASON)(
    lambda ctx: _sea.detect_upsets(ctx.season_code, ctx.round_number, ctx.matches, ctx.season_context)
    if ctx.season_context is not None else []
)
register("season_scoring_leader", Scope.SEASON)(
    lambda ctx: _agg.detect_season_scoring_leader(ctx.season_code, ctx.round_number, ctx.season)
)
register("season_rebounding_leader", Scope.SEASON)(
    lambda ctx: _agg.detect_season_rebounding_leader(ctx.season_code, ctx.round_number, ctx.season)
)
register("season_assist_leader", Scope.SEASON)(
    lambda ctx: _agg.detect_season_assist_leader(ctx.season_code, ctx.round_number, ctx.season)
)


def _one(story: Optional[StoryObject]) -> List[StoryObject]:
    """Wrap a single-optional detector result as a list for the collector."""
    return [story] if story is not None else []
