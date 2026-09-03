"""Season-to-date aggregation + the season-scope detectors built on it.

The round detectors need only the current round; the season detectors need the
season SO FAR. ``SeasonAggregate`` is that rolled-up view — per-player totals
across every round played — folded deterministically from the round inputs by
``build_season_aggregate`` (the application layer feeds it the rounds). Keeping
it a plain fold means a test can build one directly and the domain stays pure.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

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
    # Season FEB Rating per player, averaged from the per-game notes. Kept as a
    # separate side map rather than on PlayerSeasonLine because it requires per-
    # game shooting data (which lives in the boxscore blobs, not in the
    # SeasonPlayerStats view the aggregate is folded from). The adapter fills
    # it; a domain-only fold defaults to an empty map so the season quintet
    # detectors self-skip cleanly instead of crowning someone with nothing.
    feb_by_player: Dict[str, float] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.feb_by_player is None:  # frozen dataclass: bypass to set default
            object.__setattr__(self, "feb_by_player", {})


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


# ---------------------------------------------------------------------------
# Season quintets — top 5 by FEB Rating and the ideal 5 by position
# ---------------------------------------------------------------------------

# The season quintet floor scales with the round so a card at jornada 8 does
# not accept the same "6 games" that a card at jornada 30 does. A player who
# missed 40%+ of the year cannot be in a season ideal five — the claim would
# not survive a reader who follows the league. Below jornada 10 nothing is
# really "de temporada" yet, so 6 is the absolute minimum floor.
SEASON_QUINTET_MIN_ABSOLUTE = 6
SEASON_QUINTET_MIN_RATIO = 0.6  # of the current round


def season_quintet_min_games(round_number: int) -> int:
    """Games-played floor for a season quintet published at ``round_number``.
    max(6, 60% of rounds played)."""
    return max(SEASON_QUINTET_MIN_ABSOLUTE, math.ceil(round_number * SEASON_QUINTET_MIN_RATIO))


# Kept as a backwards-compatible alias so tests that referenced it still read.
SEASON_QUINTET_MIN_GAMES = SEASON_QUINTET_MIN_ABSOLUTE


def _season_lineup_row(
    line: PlayerSeasonLine, rating: float, *, extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    row = {
        "player_external_id": line.player_external_id,
        "player_name": display_name(line.player_name),
        "team_external_id": line.team_external_id,
        "team_name": line.team_name,
        "points": line.points,        # totals — the "24 pts / 8 reb" line is
        "rebounds": line.rebounds,    # framed as "por partido" by the render
        "assists": line.assists,
        "rating": round(rating, 1),
        # The context line under the name reads as PPP/RPP/APP because a season
        # quintet ranks per-game averages, not totals — a 300-rebound big does
        # not sit above a 12-per-game one just because they played more.
        "points_per_game": round(line.points / line.games, 1) if line.games else 0.0,
        "rebounds_per_game": round(line.rebounds / line.games, 1) if line.games else 0.0,
        "assists_per_game": round(line.assists / line.games, 1) if line.games else 0.0,
        "games_played": line.games,
    }
    if extra:
        row.update(extra)
    return row


def detect_season_best_five(
    season_code: str, round_number: int, season: Optional[SeasonAggregate],
) -> List[StoryObject]:
    """The five players with the highest SEASON FEB Rating. Self-skips without
    an aggregate, without a per-player FEB map, or with fewer than five players
    who cleared the games floor — a quintet padded with unrated names would be
    a claim the data does not support."""
    if season is None or not season.feb_by_player:
        return []
    floor = season_quintet_min_games(round_number)
    by_id = {p.player_external_id: p for p in season.players}
    rated = [
        (by_id[pid], feb)
        for pid, feb in season.feb_by_player.items()
        if pid in by_id and by_id[pid].games >= floor
    ]
    if len(rated) < 5:
        return []
    rated.sort(key=lambda pr: (-pr[1], -pr[0].points, pr[0].player_external_id))
    top = rated[:5]
    lineup = [
        {"rank": i, **_season_lineup_row(p, r)}
        for i, (p, r) in enumerate(top, start=1)
    ]
    from .rating import FEB_RATING_VERSION
    return [StoryObject(
        story_type=StoryType.BEST_FIVE_SEASON,
        season_code=season.season_code,
        round_number=round_number,
        entities=StoryEntities(),
        facts={
            "lineup": lineup, "count": 5,
            "rating_version": FEB_RATING_VERSION,
            "section_label": "El quinteto de la temporada",
            "metric_label": "FEB RATING /10",
            "count_label": "Top 5",
        },
        source_refs={
            "season_player_stats": f"2afeb_score://season_player_stats/{season.season_code}",
        },
    )]


def detect_season_best_five_ideal(
    season_code: str, round_number: int, season: Optional[SeasonAggregate],
    bio: Optional[Any] = None,
) -> List[StoryObject]:
    """The ideal season five by position: the highest-rated player at each of
    the five court positions. Needs a rated player at EVERY position — a hole
    at one position yields no card rather than a four-player quintet."""
    if season is None or not season.feb_by_player or bio is None:
        return []
    from .bio import POSITIONS

    floor = season_quintet_min_games(round_number)
    by_id = {p.player_external_id: p for p in season.players}
    best: Dict[str, tuple] = {}
    for pid, feb in season.feb_by_player.items():
        line = by_id.get(pid)
        if line is None or line.games < floor:
            continue
        pos = bio.position(pid)
        if pos is None:
            continue
        cur = best.get(pos)
        if cur is None or feb > cur[1] or (feb == cur[1] and line.points > cur[0].points):
            best[pos] = (line, feb)
    if any(pos not in best for pos in POSITIONS):
        return []
    lineup = []
    for pos in POSITIONS:
        line, feb = best[pos]
        lineup.append(_season_lineup_row(line, feb, extra={"position": pos}))
    from .rating import FEB_RATING_VERSION
    return [StoryObject(
        story_type=StoryType.BEST_FIVE_IDEAL_SEASON,
        season_code=season.season_code,
        round_number=round_number,
        entities=StoryEntities(),
        facts={
            "lineup": lineup, "count": 5,
            "rating_version": FEB_RATING_VERSION,
            "section_label": "El quinteto ideal de la temporada",
        },
        source_refs={
            "season_player_stats": f"2afeb_score://season_player_stats/{season.season_code}",
        },
    )]
