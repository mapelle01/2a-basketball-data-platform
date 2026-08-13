from datetime import datetime
from uuid import uuid4

import pytest

from feb_score.domain.errors import InvalidRatingCalculation
from feb_score.domain.ratings.model import PlayerRating
from feb_score.domain.statistics.model import PlayerStats
from feb_score.domain.value_objects import ExternalId, RatingVersion, SeasonCode


def test_compute_player_rating_from_stats():
    player_external_id = ExternalId("pl-987")
    season_code = SeasonCode("2025-2026")
    stats = [
        PlayerStats(
            player_external_id="pl-987",
            team_external_id="team-home",
            points=20,
            rebounds=10,
            assists=5,
            turnovers=2,
        ),
        PlayerStats(
            player_external_id="pl-987",
            team_external_id="team-home",
            points=25,
            rebounds=8,
            assists=6,
            turnovers=3,
        ),
    ]

    rating = PlayerRating.compute_from_stats(
        player_external_id=player_external_id,
        season_code=season_code,
        stats=stats,
        rating_version=RatingVersion("v1.0"),
        calculated_at=datetime.utcnow(),
    )

    assert rating.player_external_id == player_external_id
    assert rating.rating_value.value >= 0
    assert rating.rating_version.value == "v1.0"


def test_compute_player_rating_requires_stats():
    with pytest.raises(InvalidRatingCalculation):
        PlayerRating.compute_from_stats(
            player_external_id=ExternalId("pl-987"),
            season_code=SeasonCode("2025-2026"),
            stats=[],
            rating_version=RatingVersion("v1.0"),
            calculated_at=datetime.utcnow(),
        )


def test_player_rating_to_dict_is_reproducible():
    stats = [
        PlayerStats(
            player_external_id="pl-987",
            team_external_id="team-home",
            points=20,
            rebounds=10,
            assists=5,
            turnovers=2,
        ),
    ]
    rating = PlayerRating.compute_from_stats(
        player_external_id=ExternalId("pl-987"),
        season_code=SeasonCode("2025-2026"),
        stats=stats,
        rating_version=RatingVersion("v1.0"),
        calculated_at=datetime(2026, 2, 1, 12, 0),
    )

    payload = rating.to_dict()
    assert payload["player_external_id"] == "pl-987"
    assert payload["rating_version"] == "v1.0"
    assert payload["source_stats"] == [stats[0].to_dict()]
