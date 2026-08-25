"""Insight Engine — deterministic story detection.

Pure functions: consume DTOs from the data platform (Match, PlayerStats,
TeamStats) and emit StoryObject instances. No repositories, no IO, no LLM.
Every emitted fact is traceable to a specific data source recorded in
``source_refs`` — the FactValidator enforces this invariant later.

v1 detectors delivered:
  - detect_match_final   (one story per finalized match)
  - detect_player_of_round (best impact score across the round)
  - detect_round_recap    (aggregate summary per round)

Future detectors slot in without touching existing ones.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .names import display_name
from .story import StoryEntities, StoryObject, StoryType


# ---------------------------------------------------------------------------
# Detector inputs — tiny DTOs so the engine stays domain-pure.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MatchFactsInput:
    external_id: str
    season_code: str
    round_number: int
    home_team_external_id: str
    away_team_external_id: str
    home_team_name: Optional[str]
    away_team_name: Optional[str]
    home_score: int
    away_score: int
    scheduled_at: datetime

    @property
    def winner_id(self) -> str:
        return self.home_team_external_id if self.home_score >= self.away_score else self.away_team_external_id

    @property
    def loser_id(self) -> str:
        return self.away_team_external_id if self.home_score >= self.away_score else self.home_team_external_id


@dataclass(frozen=True)
class PlayerLineInput:
    player_external_id: str
    player_name: Optional[str]
    team_external_id: str
    team_name: Optional[str]
    match_external_id: str
    points: int
    rebounds: int
    assists: int
    steals: int = 0
    blocks: int = 0
    turnovers: int = 0
    minutes: float = 0.0
    # Shooting / fouls — OPTIONAL. The domain PlayerStats does not carry these
    # per player yet (only TeamStats does), so they arrive as None today and the
    # shooting detectors self-skip. When the boxscore ingestion plumbs per-player
    # shooting through, these fill in and the detectors light up — no rewrite.
    field_goals_made: Optional[int] = None
    field_goals_attempted: Optional[int] = None
    three_points_made: Optional[int] = None
    three_points_attempted: Optional[int] = None
    free_throws_made: Optional[int] = None
    free_throws_attempted: Optional[int] = None
    fouls: Optional[int] = None
    fouls_received: Optional[int] = None

    @property
    def impact_score(self) -> float:
        return (
            self.points
            + self.rebounds * 1.2
            + self.assists * 1.5
            + self.steals * 2.0
            + self.blocks * 1.5
            - self.turnovers
        )

    @property
    def has_shooting(self) -> bool:
        """True when per-player shooting data is present (attempts recorded)."""
        return self.field_goals_attempted is not None

    @staticmethod
    def _pct(made: Optional[int], att: Optional[int]) -> Optional[float]:
        if made is None or att is None or att == 0:
            return None
        return round(100.0 * made / att, 1)

    @property
    def field_goal_pct(self) -> Optional[float]:
        return self._pct(self.field_goals_made, self.field_goals_attempted)

    @property
    def three_point_pct(self) -> Optional[float]:
        return self._pct(self.three_points_made, self.three_points_attempted)


# ---------------------------------------------------------------------------
# Detectors
# ---------------------------------------------------------------------------


def detect_match_final(match: MatchFactsInput) -> StoryObject:
    facts = {
        "home_team_external_id": match.home_team_external_id,
        "away_team_external_id": match.away_team_external_id,
        "home_team_name": match.home_team_name,
        "away_team_name": match.away_team_name,
        "home_score": match.home_score,
        "away_score": match.away_score,
        "margin": abs(match.home_score - match.away_score),
        "scheduled_at": match.scheduled_at.isoformat(),
    }
    return StoryObject(
        story_type=StoryType.MATCH_FINAL,
        season_code=match.season_code,
        round_number=match.round_number,
        entities=StoryEntities(
            match_external_id=match.external_id,
            home_team_external_id=match.home_team_external_id,
            away_team_external_id=match.away_team_external_id,
        ),
        facts=facts,
        source_refs={
            "match": f"2afeb_score://matches/{match.external_id}",
        },
    )


def detect_player_of_round(
    season_code: str,
    round_number: int,
    player_lines: Sequence[PlayerLineInput],
) -> Optional[StoryObject]:
    """Highest impact score across the round (min 2 players so ties fall out
    of scope). Returns None if no players — no invented content."""
    if not player_lines:
        return None

    best = max(player_lines, key=lambda p: (p.impact_score, p.points))

    facts = player_facts(best)
    return StoryObject(
        story_type=StoryType.PLAYER_OF_ROUND,
        season_code=season_code,
        round_number=round_number,
        entities=StoryEntities(
            player_external_id=best.player_external_id,
            team_external_id=best.team_external_id,
            match_external_id=best.match_external_id,
        ),
        facts=facts,
        source_refs={
            "player_stats": (
                f"2afeb_score://match_player_stats/{best.match_external_id}/"
                f"{best.player_external_id}"
            ),
        },
    )


def detect_round_recap(
    season_code: str,
    round_number: int,
    matches: Sequence[MatchFactsInput],
    player_lines: Sequence[PlayerLineInput],
) -> Optional[StoryObject]:
    if not matches:
        return None

    biggest_win = max(matches, key=lambda m: abs(m.home_score - m.away_score))
    closest_game = min(matches, key=lambda m: abs(m.home_score - m.away_score))

    top_scorer = max(player_lines, key=lambda p: p.points) if player_lines else None

    def _winner(m: MatchFactsInput) -> Dict[str, Any]:
        if m.home_score >= m.away_score:
            return {"team_external_id": m.home_team_external_id, "team_name": m.home_team_name}
        return {"team_external_id": m.away_team_external_id, "team_name": m.away_team_name}

    facts: Dict[str, Any] = {
        "matches_played": len(matches),
        "biggest_win_margin": abs(biggest_win.home_score - biggest_win.away_score),
        "biggest_win_match_external_id": biggest_win.external_id,
        "biggest_win_winner": _winner(biggest_win),
        "closest_game_margin": abs(closest_game.home_score - closest_game.away_score),
        "closest_game_match_external_id": closest_game.external_id,
    }
    if top_scorer:
        facts.update({
            "top_scorer_external_id": top_scorer.player_external_id,
            "top_scorer_name": display_name(top_scorer.player_name),
            "top_scorer_team_external_id": top_scorer.team_external_id,
            "top_scorer_team_name": top_scorer.team_name,
            "top_scorer_points": top_scorer.points,
        })

    source_refs = {
        "matches": (
            f"2afeb_score://seasons/{season_code}/rounds/{round_number}/matches"
        ),
        "biggest_win_match": (
            f"2afeb_score://matches/{biggest_win.external_id}"
        ),
        "closest_game_match": (
            f"2afeb_score://matches/{closest_game.external_id}"
        ),
    }

    return StoryObject(
        story_type=StoryType.ROUND_RECAP,
        season_code=season_code,
        round_number=round_number,
        entities=StoryEntities(),
        facts=facts,
        source_refs=source_refs,
    )


# ---------------------------------------------------------------------------
# Additional deterministic detectors (round data only — no season context)
# ---------------------------------------------------------------------------

BLOWOUT_MARGIN = 20  # a win by 20+ is "the rout of the round" material


def detect_biggest_win(
    season_code: str,
    round_number: int,
    matches: Sequence[MatchFactsInput],
) -> Optional[StoryObject]:
    """The largest-margin win of the round, when it qualifies as a blowout.

    Framed as its own editorial piece (distinct from the plain MATCH_FINAL of
    the same game). Returns None when no match reaches the blowout margin — no
    manufactured drama."""
    if not matches:
        return None
    match = max(matches, key=lambda m: abs(m.home_score - m.away_score))
    margin = abs(match.home_score - match.away_score)
    if margin < BLOWOUT_MARGIN:
        return None

    facts = {
        "home_team_external_id": match.home_team_external_id,
        "away_team_external_id": match.away_team_external_id,
        "home_team_name": match.home_team_name,
        "away_team_name": match.away_team_name,
        "home_score": match.home_score,
        "away_score": match.away_score,
        "margin": margin,
        "scheduled_at": match.scheduled_at.isoformat(),
    }
    return StoryObject(
        story_type=StoryType.BIGGEST_WIN,
        season_code=season_code,
        round_number=round_number,
        entities=StoryEntities(
            match_external_id=match.external_id,
            home_team_external_id=match.home_team_external_id,
            away_team_external_id=match.away_team_external_id,
        ),
        facts=facts,
        source_refs={"match": f"2afeb_score://matches/{match.external_id}"},
    )


def _count_double_digits(p: PlayerLineInput) -> int:
    return sum(1 for v in (p.points, p.rebounds, p.assists, p.steals, p.blocks) if v >= 10)


def detect_notable_performances(
    season_code: str,
    round_number: int,
    player_lines: Sequence[PlayerLineInput],
) -> List[StoryObject]:
    """Double-doubles and triple-doubles of the round (one story per player).

    Deterministic: a double-double is >=2 categories at 10+, a triple-double
    >=3. Both are demonstrable from the boxscore line alone."""
    stories: List[StoryObject] = []
    for p in player_lines:
        doubles = _count_double_digits(p)
        if doubles < 2:
            continue
        story_type = StoryType.TRIPLE_DOUBLE if doubles >= 3 else StoryType.DOUBLE_DOUBLE
        facts = player_facts(p)
        facts["double_digit_count"] = doubles
        stories.append(StoryObject(
            story_type=story_type,
            season_code=season_code,
            round_number=round_number,
            entities=StoryEntities(
                player_external_id=p.player_external_id,
                team_external_id=p.team_external_id,
                match_external_id=p.match_external_id,
            ),
            facts=facts,
            source_refs={
                "player_stats": (
                    f"2afeb_score://match_player_stats/{p.match_external_id}/"
                    f"{p.player_external_id}"
                ),
            },
        ))
    return stories


def detect_stat_leaderboard(
    season_code: str,
    round_number: int,
    player_lines: Sequence[PlayerLineInput],
    top_n: int = 5,
) -> Optional[StoryObject]:
    """The round's top scorers as a ranking (name, team, points, FEB Rating).
    Needs at least 3 players so a ranking is meaningful."""
    from .rating import FEB_RATING_VERSION, feb_rating

    if len(player_lines) < 3:
        return None
    ordered = sorted(player_lines, key=lambda p: (-p.points, p.player_external_id))[:top_n]
    leaders = [
        {
            "rank": i,
            "player_external_id": p.player_external_id,
            "player_name": display_name(p.player_name),
            "team_external_id": p.team_external_id,
            "team_name": p.team_name,
            "points": p.points,
            "rebounds": p.rebounds,
            "assists": p.assists,
            "rating": _rating_of(p),
        }
        for i, p in enumerate(ordered, start=1)
    ]
    return StoryObject(
        story_type=StoryType.STAT_LEADERBOARD,
        season_code=season_code,
        round_number=round_number,
        entities=StoryEntities(),
        facts={
            "leaders": leaders,
            "count": len(leaders),
            "rating_version": FEB_RATING_VERSION,
        },
        source_refs={
            "player_stats": (
                f"2afeb_score://seasons/{season_code}/rounds/{round_number}/player_stats"
            ),
        },
    )


# ---------------------------------------------------------------------------
# Curious & shooting player angles (single-player, framed by a chosen hero stat)
# ---------------------------------------------------------------------------
# These reuse the player card but pick their OWN hero stat (assists, minutes,
# threes…) via display hints in the facts, so the same template tells a
# different story. Shooting detectors self-skip when per-player shooting data is
# absent (``has_shooting``), so they stay dormant until the ingestion carries it.

MINUTES_HEAVY = 35.0        # a 35'+ night on a 40' game = a real workhorse
PLAYMAKER_MIN_ASSISTS = 8   # 8+ assists = a genuine facilitator night
SHARP_MIN_THREES = 5        # 5+ made threes = a shooting show
PERFECT_MIN_FG_ATT = 5      # 5+ attempts, no misses = a perfect night
# Measured over 2,607 real player-lines (2024-25, rounds 18-26): robos+tapones
# has a median of 1 and a 95th percentile of 3. At 5 the detector sees ~2.3
# candidates a round (the top 0.8% of lines) and fires in 8 rounds out of 9 —
# rare enough to mean something, common enough to be a lane. At 4 it would be
# 10 a round, i.e. an ordinary night dressed up as a story.
DEFENSIVE_MIN_ACTIONS = 5   # steals + blocks


def _rating_of(p: PlayerLineInput) -> Optional[float]:
    """The FEB Rating for a line, or None when it cannot be rated on the same
    basis as the rest (too few minutes, or no shooting data). ONE mapping from
    a player line to the mark, so no call site can rate on a different input
    set and produce a note that is not comparable."""
    from .rating import feb_rating

    return feb_rating(
        p.points, p.rebounds, p.assists, p.steals, p.blocks, p.turnovers,
        minutes=p.minutes,
        field_goals_made=p.field_goals_made,
        field_goals_attempted=p.field_goals_attempted,
        free_throws_made=p.free_throws_made or 0,
        free_throws_attempted=p.free_throws_attempted or 0,
        three_points_made=p.three_points_made or 0,
        fouls=p.fouls or 0,
        fouls_received=p.fouls_received or 0,
    )


def player_facts(p: PlayerLineInput) -> Dict[str, Any]:
    """THE canonical fact set for a player-card story.

    Includes the FEB Rating: it is a derived, versioned, deterministic fact (like
    impact_score), so every player card can show the signature mark and the
    validator can check it. Building every player story through here keeps the
    rating from silently missing on some card types.
    """
    from .rating import FEB_RATING_VERSION, feb_rating

    return {
        "player_external_id": p.player_external_id,
        "player_name": display_name(p.player_name),
        "team_external_id": p.team_external_id,
        "team_name": p.team_name,
        "points": p.points,
        "rebounds": p.rebounds,
        "assists": p.assists,
        "steals": p.steals,
        "blocks": p.blocks,
        "turnovers": p.turnovers,
        "minutes": p.minutes,
        "minutes_played": int(round(p.minutes)),
        "impact_score": round(p.impact_score, 1),
        "rating": _rating_of(p),
        "rating_version": FEB_RATING_VERSION,
        "match_external_id": p.match_external_id,
    }


def _player_story(story_type: StoryType, season_code: str, round_number: int,
                  p: PlayerLineInput, extra: Dict[str, Any]) -> StoryObject:
    facts = player_facts(p)
    facts.update(extra)
    return StoryObject(
        story_type=story_type,
        season_code=season_code,
        round_number=round_number,
        entities=StoryEntities(
            player_external_id=p.player_external_id,
            team_external_id=p.team_external_id,
            match_external_id=p.match_external_id,
        ),
        facts=facts,
        source_refs={
            "player_stats": (
                f"2afeb_score://match_player_stats/{p.match_external_id}/"
                f"{p.player_external_id}"
            ),
        },
    )


def detect_iron_man(
    season_code: str, round_number: int, player_lines: Sequence[PlayerLineInput],
) -> Optional[StoryObject]:
    """The workhorse of the round — most minutes, when it clears a heavy load.
    Skips silently when minutes aren't recorded (all 0)."""
    heavy = [p for p in player_lines if p.minutes >= MINUTES_HEAVY]
    if not heavy:
        return None
    p = max(heavy, key=lambda x: (x.minutes, x.points))
    return _player_story(StoryType.IRON_MAN, season_code, round_number, p, {
        "hero_value": int(round(p.minutes)), "hero_label": "MIN",
        "secondary": [[p.points, "PTS"], [p.rebounds, "REB"]],
        "badge_label": "MARATÓN", "section_label": "El más trabajador",
    })


def detect_playmaker(
    season_code: str, round_number: int, player_lines: Sequence[PlayerLineInput],
) -> Optional[StoryObject]:
    """The round's chief facilitator — the assist leader, when assists reach a
    real playmaking night (frames a card by assists, not points)."""
    eligible = [p for p in player_lines if p.assists >= PLAYMAKER_MIN_ASSISTS]
    if not eligible:
        return None
    p = max(eligible, key=lambda x: (x.assists, x.points))
    return _player_story(StoryType.PLAYMAKER, season_code, round_number, p, {
        "hero_value": p.assists, "hero_label": "AST",
        "secondary": [[p.points, "PTS"], [p.rebounds, "REB"]],
        "badge_label": "DIRECTOR", "section_label": "El director de juego",
    })


def detect_defensive_anchor(
    season_code: str, round_number: int, player_lines: Sequence[PlayerLineInput],
) -> Optional[StoryObject]:
    """The best defensive night of the round — steals plus blocks.

    Defence barely registers in a boxscore, so without a card of its own it
    never gets told: five blocks in a five-point night loses every ranking to
    the scorers. The hero number is the SUM, with both parts shown beside it so
    a reader can check the arithmetic rather than take it on trust.
    """
    eligible = [
        p for p in player_lines
        if (p.steals + p.blocks) >= DEFENSIVE_MIN_ACTIONS
    ]
    if not eligible:
        return None
    p = max(eligible, key=lambda x: (x.steals + x.blocks, x.points))
    actions = p.steals + p.blocks
    return _player_story(StoryType.DEFENSIVE_ANCHOR, season_code, round_number, p, {
        "defensive_actions": actions,
        "hero_value": actions, "hero_label": "ROB+TAP",
        "secondary": [[p.steals, "ROB"], [p.blocks, "TAP"]],
        "badge_label": "DEFENSA", "section_label": "El muro de la jornada",
    })


def detect_sharpshooter(
    season_code: str, round_number: int, player_lines: Sequence[PlayerLineInput],
) -> Optional[StoryObject]:
    """The best 3-point game of the round (most made, then best %). Needs
    per-player shooting data — dormant until the ingestion carries it."""
    eligible = [
        p for p in player_lines
        if p.has_shooting and (p.three_points_made or 0) >= SHARP_MIN_THREES
    ]
    if not eligible:
        return None
    p = max(eligible, key=lambda x: (x.three_points_made, x.three_point_pct or 0.0, x.points))
    return _player_story(StoryType.SHARPSHOOTER, season_code, round_number, p, {
        "three_points_made": p.three_points_made,
        "three_points_attempted": p.three_points_attempted,
        "three_point_pct": p.three_point_pct,
        "hero_value": p.three_points_made, "hero_label": "TRIPLES",
        "secondary": [[p.points, "PTS"], [p.three_points_attempted, "INT"]],
        "badge_label": "SNIPER", "section_label": "El tirador de la jornada",
    })


def detect_perfect_night(
    season_code: str, round_number: int, player_lines: Sequence[PlayerLineInput],
) -> Optional[StoryObject]:
    """A player who didn't miss from the field, with real volume. Needs
    per-player shooting data — dormant until the ingestion carries it."""
    eligible = [
        p for p in player_lines
        if p.has_shooting and (p.field_goals_attempted or 0) >= PERFECT_MIN_FG_ATT
        and p.field_goals_made == p.field_goals_attempted
    ]
    if not eligible:
        return None
    p = max(eligible, key=lambda x: (x.field_goals_attempted, x.points))
    return _player_story(StoryType.PERFECT_NIGHT, season_code, round_number, p, {
        "field_goals_made": p.field_goals_made,
        "field_goals_attempted": p.field_goals_attempted,
        "field_goal_pct": p.field_goal_pct,
        "hero_value": p.points, "hero_label": "PTS",
        "secondary": [[p.field_goals_made, "TC"], [p.rebounds, "REB"]],
        "badge_label": "SIN FALLO", "section_label": "Noche perfecta",
    })


DUO_MIN_COMBINED = 35  # two teammates must combine for a real haul to be a story


def detect_best_duo(
    season_code: str, round_number: int, player_lines: Sequence[PlayerLineInput],
) -> Optional[StoryObject]:
    """The round's best pair of TEAMMATES: the two highest scorers on the same
    team in the same game, by combined points. Needs two players from one
    team-game; skips below the combined threshold (no manufactured duo)."""
    from collections import defaultdict

    from .rating import FEB_RATING_VERSION, feb_rating

    groups: Dict[tuple, List[PlayerLineInput]] = defaultdict(list)
    for p in player_lines:
        groups[(p.match_external_id, p.team_external_id)].append(p)

    best: Optional[tuple] = None  # (combined, p1, p2)
    for members in groups.values():
        if len(members) < 2:
            continue
        p1, p2 = sorted(members, key=lambda x: (-x.points, x.player_external_id))[:2]
        combined = p1.points + p2.points
        if best is None or combined > best[0]:
            best = (combined, p1, p2)
    if best is None or best[0] < DUO_MIN_COMBINED:
        return None
    combined, p1, p2 = best

    def _rt(p: PlayerLineInput) -> float:
        return _rating_of(p)

    facts = {
        "team_external_id": p1.team_external_id,
        "team_name": p1.team_name,
        "match_external_id": p1.match_external_id,
        "p1_external_id": p1.player_external_id, "p1_name": display_name(p1.player_name),
        "p1_points": p1.points, "p1_rating": _rt(p1),
        "p2_external_id": p2.player_external_id, "p2_name": display_name(p2.player_name),
        "p2_points": p2.points, "p2_rating": _rt(p2),
        "combined_points": combined,
        "rating_version": FEB_RATING_VERSION,
    }
    return StoryObject(
        story_type=StoryType.BEST_DUO,
        season_code=season_code,
        round_number=round_number,
        entities=StoryEntities(
            team_external_id=p1.team_external_id, match_external_id=p1.match_external_id,
        ),
        facts=facts,
        source_refs={
            "player_stats": (
                f"2afeb_score://match_player_stats/{p1.match_external_id}"
            ),
        },
    )


# ---------------------------------------------------------------------------
# Round-level convenience entry point
# ---------------------------------------------------------------------------


def detect_all_for_round(
    season_code: str,
    round_number: int,
    matches: Sequence[MatchFactsInput],
    player_lines: Sequence[PlayerLineInput],
) -> List[StoryObject]:
    """Run every ROUND-scope detector and return the raw stories. Delegates to
    the detector registry (the single source of truth); kept as a convenience
    entry point. The Planner scores/selects; this only emits."""
    from .registry import DetectionContext, Scope, run_detectors  # lazy: avoid import cycle

    ctx = DetectionContext(
        season_code=season_code, round_number=round_number,
        matches=tuple(matches), player_lines=tuple(player_lines),
    )
    return run_detectors(ctx, {Scope.ROUND})
