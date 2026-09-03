"""Season-to-date aggregation + the season-scope detectors built on it.

The round detectors need only the current round; the season detectors need the
season SO FAR. ``SeasonAggregate`` is that rolled-up view — per-player totals
across every round played — folded deterministically from the round inputs by
``build_season_aggregate`` (the application layer feeds it the rounds). Keeping
it a plain fold means a test can build one directly and the domain stays pure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from .insights import PlayerLineInput
from .names import display_name
from .rating import FEB_RATING_VERSION as _RATING_VERSION
from .story import StoryEntities, StoryObject, StoryType


@dataclass(frozen=True)
class PlayerSeasonLine:
    player_external_id: str
    games: int
    points: int
    rebounds: int
    assists: int
    player_name: Optional[str] = None
    team_external_id: Optional[str] = None
    team_name: Optional[str] = None
    steals: int = 0
    blocks: int = 0
    turnovers: int = 0
    # Extended fields for the season-wide FEB Rating. Minutes are 0 when the
    # source can't supply them (older fixtures, or matches from a scraper that
    # dropped the column). Shooting totals stay None to keep "unknown" distinct
    # from "0 attempts": one game with a null field_goals_attempted makes the
    # whole season total None, because we cannot honestly report a rate.
    minutes: float = 0.0
    field_goals_made: Optional[int] = None
    field_goals_attempted: Optional[int] = None
    # True iff THIS season is the player's first appearance in the league
    # according to every season we have on record. The adapter fills it by
    # cross-checking prior-season player rosters — until historical seasons are
    # ingested, every player looks like a debutant, so the best-debut detector
    # must self-skip when there is no prior-season baseline. Kept False by
    # default so a fold over a single season never wrongly flags anyone.
    is_league_debut: bool = False

    @property
    def ppg(self) -> float:
        return round(self.points / self.games, 1) if self.games else 0.0

    @property
    def rating(self) -> Optional[float]:
        """The FEB Rating of this player's AVERAGE game — or None when the
        minutes or shooting data isn't there to compute it honestly.

        Ratings the average game (not the totals), so the value stays on the
        same 0..10 scale as a boxscore rating and a season card can sit next to
        a match card without misleading anyone."""
        if not self.games or self.minutes_per_game is None or self.minutes_per_game <= 0:
            return None
        if self.field_goals_made is None or self.field_goals_attempted is None:
            return None
        from .rating import feb_rating

        g = self.games
        return feb_rating(
            round(self.points / g), round(self.rebounds / g), round(self.assists / g),
            round(self.steals / g), round(self.blocks / g), round(self.turnovers / g),
            minutes=self.minutes_per_game,
            field_goals_made=round(self.field_goals_made / g),
            field_goals_attempted=round(self.field_goals_attempted / g),
        )

    @property
    def minutes_per_game(self) -> Optional[float]:
        if not self.games or self.minutes <= 0:
            return None
        return round(self.minutes / self.games, 1)


@dataclass(frozen=True)
class SeasonAggregate:
    season_code: str
    players: Tuple[PlayerSeasonLine, ...] = ()


def build_season_aggregate(
    season_code: str, rounds: Sequence[Sequence[PlayerLineInput]],
) -> SeasonAggregate:
    """Fold every round's player lines into per-player season totals. The latest
    non-empty name/team seen wins (catalogs fill in over the season). Minutes
    are summed straight; shooting totals stay None if ANY game contributed a
    null attempt/make, because a rate over an incomplete sample would lie."""
    acc: Dict[str, Dict[str, object]] = {}
    for rnd in rounds:
        for p in rnd:
            a = acc.setdefault(p.player_external_id, {
                "player_name": None, "team_external_id": p.team_external_id,
                "team_name": None, "games": 0, "points": 0, "rebounds": 0, "assists": 0,
                "steals": 0, "blocks": 0, "turnovers": 0,
                "minutes": 0.0, "fgm": 0, "fga": 0, "shooting_complete": True,
            })
            a["games"] = int(a["games"]) + 1
            a["points"] = int(a["points"]) + p.points
            a["rebounds"] = int(a["rebounds"]) + p.rebounds
            a["assists"] = int(a["assists"]) + p.assists
            a["steals"] = int(a["steals"]) + p.steals
            a["blocks"] = int(a["blocks"]) + p.blocks
            a["turnovers"] = int(a["turnovers"]) + p.turnovers
            a["minutes"] = float(a["minutes"]) + float(getattr(p, "minutes", 0.0) or 0.0)
            fgm = getattr(p, "field_goals_made", None)
            fga = getattr(p, "field_goals_attempted", None)
            if fgm is None or fga is None:
                a["shooting_complete"] = False
            elif a["shooting_complete"]:
                a["fgm"] = int(a["fgm"]) + int(fgm)
                a["fga"] = int(a["fga"]) + int(fga)
            if p.player_name:
                a["player_name"] = p.player_name
            if p.team_name:
                a["team_name"] = p.team_name
            a["team_external_id"] = p.team_external_id
    players = tuple(
        PlayerSeasonLine(
            player_external_id=pid, player_name=a["player_name"],  # type: ignore[arg-type]
            team_external_id=a["team_external_id"], team_name=a["team_name"],  # type: ignore[arg-type]
            games=int(a["games"]), points=int(a["points"]),
            rebounds=int(a["rebounds"]), assists=int(a["assists"]),
            steals=int(a["steals"]), blocks=int(a["blocks"]),
            turnovers=int(a["turnovers"]),
            minutes=float(a["minutes"]),
            field_goals_made=int(a["fgm"]) if a["shooting_complete"] else None,
            field_goals_attempted=int(a["fga"]) if a["shooting_complete"] else None,
        )
        for pid, a in acc.items()
    )
    return SeasonAggregate(season_code=season_code, players=players)


# ---------------------------------------------------------------------------
# Season-scope detectors — the season leaders (one card per category)
# ---------------------------------------------------------------------------

SEASON_LEADER_MIN_GAMES = 3  # need a real sample before crowning a leader


def _season_leader(
    season: Optional[SeasonAggregate],
    round_number: int,
    *,
    total_of,                # PlayerSeasonLine -> int (the season total to rank on)
    story_type: StoryType,
    hero_label: str,
    per_game_label: str,
    section_label: str,
    badge_label: str,
    min_games: int = SEASON_LEADER_MIN_GAMES,
) -> List[StoryObject]:
    """The season leader for a stat (max season total, min games). Self-skips
    with no aggregate — dormant until the adapter feeds one. Reuses the player
    card, framed by the leading total."""
    if season is None:
        return []
    eligible = [p for p in season.players if p.games >= min_games and total_of(p) > 0]
    if not eligible:
        return []
    leader = max(eligible, key=lambda p: (total_of(p), p.player_external_id))
    total = total_of(leader)
    per_game = round(total / leader.games, 1) if leader.games else 0.0
    facts = {
        "player_external_id": leader.player_external_id,
        "player_name": display_name(leader.player_name),
        "team_external_id": leader.team_external_id,
        "team_name": leader.team_name,
        "points": leader.points,
        "rebounds": leader.rebounds,
        "assists": leader.assists,
        "games_played": leader.games,
        "season_total": total,
        "per_game": per_game,
        # The FEB Rating of the leader's average game, so the season cards carry
        # the signature mark like every other player card (None → no band drawn).
        "rating": leader.rating,
        "rating_version": _RATING_VERSION,
        "impact_score": round(leader.points + leader.rebounds * 1.2 + leader.assists * 1.5, 1),
        # Player-card hero hints (reuses player_of_round, framed as the season lead).
        "hero_value": total, "hero_label": hero_label,
        "secondary": [[leader.games, "PART"], [per_game, per_game_label]],
        "badge_label": badge_label,
        "section_label": section_label,
    }
    return [StoryObject(
        story_type=story_type,
        season_code=season.season_code,
        round_number=round_number,
        entities=StoryEntities(
            player_external_id=leader.player_external_id,
            team_external_id=leader.team_external_id,
        ),
        facts=facts,
        source_refs={
            "season_player_stats": (
                f"2afeb_score://season_player_stats/{season.season_code}/"
                f"{leader.player_external_id}"
            ),
        },
    )]


def detect_season_scoring_leader(
    season_code: str, round_number: int, season: Optional[SeasonAggregate],
) -> List[StoryObject]:
    return _season_leader(
        season, round_number, total_of=lambda p: p.points,
        story_type=StoryType.TOP_SCORER, hero_label="PTS TOTALES", per_game_label="PPP",
        section_label="Máximo anotador de la temporada", badge_label="MÁX. ANOTADOR",
    )


def detect_season_rebounding_leader(
    season_code: str, round_number: int, season: Optional[SeasonAggregate],
) -> List[StoryObject]:
    return _season_leader(
        season, round_number, total_of=lambda p: p.rebounds,
        story_type=StoryType.TOP_REBOUNDER, hero_label="REB TOTALES", per_game_label="RPP",
        section_label="Máximo reboteador de la temporada", badge_label="MÁX. REBOTES",
    )


def detect_season_assist_leader(
    season_code: str, round_number: int, season: Optional[SeasonAggregate],
) -> List[StoryObject]:
    return _season_leader(
        season, round_number, total_of=lambda p: p.assists,
        story_type=StoryType.TOP_ASSIST_PROVIDER, hero_label="AST TOTALES", per_game_label="APP",
        section_label="Máximo asistente de la temporada", badge_label="MÁX. ASISTENCIAS",
    )
