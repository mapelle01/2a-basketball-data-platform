from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Iterable, List

from ..common import AggregateRoot
from ..errors import InvalidRatingCalculation
from ..statistics.model import PlayerStats
from ..value_objects import ExternalId, RatingValue, RatingVersion, SeasonCode


@dataclass
class PlayerRating(AggregateRoot):
    player_external_id: ExternalId
    season_code: SeasonCode
    rating_value: RatingValue
    rating_version: RatingVersion
    calculated_at: datetime
    source_stats: List[Dict[str, object]] = field(default_factory=list)

    @classmethod
    def compute_from_stats(
        cls,
        player_external_id: ExternalId,
        season_code: SeasonCode,
        stats: Iterable[PlayerStats],
        rating_version: RatingVersion,
        calculated_at: datetime,
    ) -> PlayerRating:
        stats_list = list(stats)
        if not stats_list:
            raise InvalidRatingCalculation("Cannot compute rating without player stats")

        total_points = sum(entry.points for entry in stats_list)
        total_rebounds = sum(entry.rebounds for entry in stats_list)
        total_assists = sum(entry.assists for entry in stats_list)
        total_turnovers = sum(entry.turnovers for entry in stats_list)
        games = len(stats_list)
        rating_score = (
            total_points * 1.0
            + total_rebounds * 1.2
            + total_assists * 1.5
            - total_turnovers * 0.8
        ) / games

        if rating_score < 0:
            raise InvalidRatingCalculation("Computed rating must be non-negative")

        return PlayerRating(
            player_external_id=player_external_id,
            season_code=season_code,
            rating_value=RatingValue(round(rating_score, 2)),
            rating_version=rating_version,
            calculated_at=calculated_at,
            source_stats=[stat.to_dict() for stat in stats_list],
        )

    def to_dict(self) -> Dict[str, object]:
        return {
            "player_external_id": str(self.player_external_id),
            "season_code": str(self.season_code),
            "rating_value": self.rating_value.value,
            "rating_version": str(self.rating_version),
            "calculated_at": self.calculated_at.isoformat(),
            "source_stats": self.source_stats,
        }
