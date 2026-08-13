from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Iterable, List

from ..common import AggregateRoot
from ..errors import InvalidLeaderboardCategory
from ..match.model import Match
from ..value_objects import LeaderboardId, SeasonCode

LEADERBOARD_CATEGORIES = {
    "points": "points",
    "points_per_game": "points",
    "rebounds": "rebounds",
    "rebounds_per_game": "rebounds",
    "assists": "assists",
    "assists_per_game": "assists",
    "steals": "steals",
    "steals_per_game": "steals",
    "blocks": "blocks",
    "blocks_per_game": "blocks",
    "turnovers": "turnovers",
    "turnovers_per_game": "turnovers",
}


@dataclass(frozen=True)
class LeaderboardEntry:
    player_external_id: str
    team_external_id: str
    games: int
    value: float


@dataclass
class Leaderboard(AggregateRoot):
    leaderboard_id: LeaderboardId
    season_code: SeasonCode
    category: str
    generated_at: datetime
    min_games: int
    entries: List[LeaderboardEntry] = field(default_factory=list)

    @classmethod
    def from_matches(
        cls,
        season_code: SeasonCode,
        category: str,
        matches: Iterable[Match],
        min_games: int,
        top_n: int,
        generated_at: datetime,
    ) -> "Leaderboard":
        stat_field = LEADERBOARD_CATEGORIES.get(category)
        if stat_field is None:
            raise InvalidLeaderboardCategory(f"Unsupported leaderboard category: {category}")

        aggregates: Dict[str, Dict[str, object]] = {}
        for match in matches:
            if match.status.value != "FINALIZED" or str(match.season_code) != str(season_code):
                continue
            for stat in match.player_stats:
                agg = aggregates.setdefault(
                    stat.player_external_id,
                    {"team_external_id": stat.team_external_id, "games": 0, "total": 0.0},
                )
                agg["total"] += float(getattr(stat, stat_field))
                agg["games"] += 1

        entries: List[LeaderboardEntry] = []
        for player_id, agg in aggregates.items():
            games = int(agg["games"])
            if games < min_games:
                continue
            entries.append(
                LeaderboardEntry(
                    player_external_id=player_id,
                    team_external_id=str(agg["team_external_id"]),
                    games=games,
                    value=round(float(agg["total"]) / games, 2),
                )
            )

        entries.sort(key=lambda entry: (-entry.value, entry.player_external_id))
        if top_n is not None:
            entries = entries[:top_n]

        return cls(
            leaderboard_id=LeaderboardId(str(uuid.uuid4())),
            season_code=season_code,
            category=category,
            generated_at=generated_at,
            min_games=min_games,
            entries=entries,
        )