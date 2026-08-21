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

    @property
    def ppg(self) -> float:
        return round(self.points / self.games, 1) if self.games else 0.0


@dataclass(frozen=True)
class SeasonAggregate:
    season_code: str
    players: Tuple[PlayerSeasonLine, ...] = ()


def build_season_aggregate(
    season_code: str, rounds: Sequence[Sequence[PlayerLineInput]],
) -> SeasonAggregate:
    """Fold every round's player lines into per-player season totals. The latest
    non-empty name/team seen wins (catalogs fill in over the season)."""
    acc: Dict[str, Dict[str, object]] = {}
    for rnd in rounds:
        for p in rnd:
            a = acc.setdefault(p.player_external_id, {
                "player_name": None, "team_external_id": p.team_external_id,
                "team_name": None, "games": 0, "points": 0, "rebounds": 0, "assists": 0,
            })
            a["games"] = int(a["games"]) + 1
            a["points"] = int(a["points"]) + p.points
            a["rebounds"] = int(a["rebounds"]) + p.rebounds
            a["assists"] = int(a["assists"]) + p.assists
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
        "player_name": leader.player_name,
        "team_external_id": leader.team_external_id,
        "team_name": leader.team_name,
        "points": leader.points,
        "rebounds": leader.rebounds,
        "assists": leader.assists,
        "games_played": leader.games,
        "season_total": total,
        "per_game": per_game,
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
