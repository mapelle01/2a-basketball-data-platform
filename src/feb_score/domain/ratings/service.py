from __future__ import annotations

from datetime import datetime
from typing import Iterable, List

from ..events import PlayerMilestoneReached, PlayerRatingComputed
from ..statistics.model import PlayerStats
from ..value_objects import EventMeta, ExternalId, RatingVersion, SeasonCode
from .model import PlayerRating

import uuid

ELITE_RATING_THRESHOLD = 80.0


class RatingComputationService:
    """Domain Service responsible for computing a player rating
    and evaluating milestone rules.

    Window semantics (all / last_5 / last_10) are a domain rule: the window
    always refers to the most recent stats ordered chronologically by
    ``played_at``. Temporal ordering therefore lives here, not in handlers.

    The milestone threshold (>= 80.0) is a domain business rule
    that does not belong in the Application Layer.
    """

    def _select_window(self, stats: List[PlayerStats], window: str) -> List[PlayerStats]:
        if window not in ("last_5", "last_10"):
            return stats
        limit = 5 if window == "last_5" else 10
        ordered = sorted(stats, key=lambda s: s.played_at or datetime.min)
        return ordered[-limit:]

    def compute_and_evaluate(
        self,
        player_external_id: ExternalId,
        season_code: SeasonCode,
        stats: Iterable[PlayerStats],
        rating_version: RatingVersion,
        calculated_at: datetime,
        actor_id: str = "system",
        window: str = "all",
    ) -> PlayerRating:
        stats_list = self._select_window(list(stats), window)

        rating = PlayerRating.compute_from_stats(
            player_external_id=player_external_id,
            season_code=season_code,
            stats=stats_list,
            rating_version=rating_version,
            calculated_at=calculated_at,
        )

        rating._record_event(
            PlayerRatingComputed(
                event_id=str(uuid.uuid4()),
                meta=EventMeta(version="1.0", produced_at=calculated_at),
                source={"origin": "system", "actor": {"id": actor_id}},
                payload={
                    "player_external_id": str(rating.player_external_id),
                    "season_code": str(rating.season_code),
                    "rating_value": rating.rating_value.value,
                    "rating_version": str(rating.rating_version),
                    "calculated_at": rating.calculated_at.isoformat(),
                },
            )
        )

        if rating.rating_value.value >= ELITE_RATING_THRESHOLD:
            rating._record_event(
                PlayerMilestoneReached(
                    event_id=str(uuid.uuid4()),
                    meta=EventMeta(version="1.0", produced_at=calculated_at),
                    source={"origin": "system", "actor": {"id": actor_id}},
                    payload={
                        "player_external_id": str(player_external_id),
                        "milestone_type": "ELITE_RATING",
                        "value": rating.rating_value.value,
                        "achieved_at": calculated_at.isoformat(),
                    },
                )
            )

        return rating
