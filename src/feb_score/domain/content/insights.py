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

    facts = {
        "player_external_id": best.player_external_id,
        "player_name": best.player_name,
        "team_external_id": best.team_external_id,
        "team_name": best.team_name,
        "points": best.points,
        "rebounds": best.rebounds,
        "assists": best.assists,
        "steals": best.steals,
        "blocks": best.blocks,
        "turnovers": best.turnovers,
        "minutes": best.minutes,
        "impact_score": round(best.impact_score, 1),
        "match_external_id": best.match_external_id,
    }
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
            "top_scorer_name": top_scorer.player_name,
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
        facts = {
            "player_external_id": p.player_external_id,
            "player_name": p.player_name,
            "team_external_id": p.team_external_id,
            "team_name": p.team_name,
            "points": p.points,
            "rebounds": p.rebounds,
            "assists": p.assists,
            "steals": p.steals,
            "blocks": p.blocks,
            "turnovers": p.turnovers,
            "minutes": p.minutes,
            "impact_score": round(p.impact_score, 1),
            "double_digit_count": doubles,
            "match_external_id": p.match_external_id,
        }
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
            "player_name": p.player_name,
            "team_external_id": p.team_external_id,
            "team_name": p.team_name,
            "points": p.points,
            "rebounds": p.rebounds,
            "assists": p.assists,
            "rating": feb_rating(p.points, p.rebounds, p.assists, p.steals, p.blocks, p.turnovers),
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


def _player_facts(p: PlayerLineInput) -> Dict[str, Any]:
    return {
        "player_external_id": p.player_external_id,
        "player_name": p.player_name,
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
        "match_external_id": p.match_external_id,
    }


def _player_story(story_type: StoryType, season_code: str, round_number: int,
                  p: PlayerLineInput, extra: Dict[str, Any]) -> StoryObject:
    facts = _player_facts(p)
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
    return _player_story(StoryType.TOP_ASSIST_PROVIDER, season_code, round_number, p, {
        "hero_value": p.assists, "hero_label": "AST",
        "secondary": [[p.points, "PTS"], [p.rebounds, "REB"]],
        "badge_label": "DIRECTOR", "section_label": "El director de juego",
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


# ---------------------------------------------------------------------------
# Round-level convenience entry point
# ---------------------------------------------------------------------------


def detect_all_for_round(
    season_code: str,
    round_number: int,
    matches: Sequence[MatchFactsInput],
    player_lines: Sequence[PlayerLineInput],
) -> List[StoryObject]:
    """Run every detector applicable to a round and return the raw stories.
    The Planner scores/selects; this only emits."""
    stories: List[StoryObject] = []
    stories.extend(detect_match_final(m) for m in matches)

    por = detect_player_of_round(season_code, round_number, player_lines)
    if por is not None:
        stories.append(por)

    recap = detect_round_recap(season_code, round_number, matches, player_lines)
    if recap is not None:
        stories.append(recap)

    biggest = detect_biggest_win(season_code, round_number, matches)
    if biggest is not None:
        stories.append(biggest)

    stories.extend(detect_notable_performances(season_code, round_number, player_lines))

    leaderboard = detect_stat_leaderboard(season_code, round_number, player_lines)
    if leaderboard is not None:
        stories.append(leaderboard)

    # Curious (live) + shooting (dormant until per-player shooting is ingested).
    for detector in (
        detect_iron_man, detect_playmaker, detect_sharpshooter, detect_perfect_night,
    ):
        story = detector(season_code, round_number, player_lines)
        if story is not None:
            stories.append(story)

    return stories
