from datetime import datetime
from uuid import uuid4

import pytest

from feb_score.domain.errors import InvalidRatingCalculation
from feb_score.domain.ratings.service import RatingComputationService, ELITE_RATING_THRESHOLD
from feb_score.domain.ratings.model import PlayerRating
from feb_score.domain.statistics.model import PlayerStats
from feb_score.domain.value_objects import ExternalId, RatingVersion, SeasonCode


def test_domain_service_deterministic_timestamps():
    """Same inputs + same calculated_at → same event timestamps."""
    service = RatingComputationService()
    fixed_time = datetime(2026, 2, 1, 12, 0, 0)
    stats = [
        PlayerStats(
            player_external_id="pl-987",
            team_external_id="team-home",
            points=20, rebounds=10, assists=5, turnovers=2,
        ),
    ]

    rating = service.compute_and_evaluate(
        player_external_id=ExternalId("pl-987"),
        season_code=SeasonCode("2025-2026"),
        stats=stats,
        rating_version=RatingVersion("v1.0"),
        calculated_at=fixed_time,
        actor_id="system-1",
    )

    events = rating.collect_events()
    assert len(events) == 1  # Below 80.0, no milestone
    assert events[0].__class__.__name__ == "PlayerRatingComputed"
    assert events[0].payload["calculated_at"] == fixed_time.isoformat()
    assert events[0].meta.produced_at == fixed_time


def test_domain_service_emits_milestone_above_threshold():
    """Rating >= 80.0 must emit both PlayerRatingComputed and PlayerMilestoneReached."""
    service = RatingComputationService()
    fixed_time = datetime(2026, 2, 1, 12, 0, 0)
    # High stats to produce rating >= 80.0
    stats = [
        PlayerStats(
            player_external_id="pl-987",
            team_external_id="team-home",
            points=100, rebounds=30, assists=20, turnovers=5,
        ),
    ]

    rating = service.compute_and_evaluate(
        player_external_id=ExternalId("pl-987"),
        season_code=SeasonCode("2025-2026"),
        stats=stats,
        rating_version=RatingVersion("v1.0"),
        calculated_at=fixed_time,
        actor_id="admin-1",
    )

    events = rating.collect_events()
    assert len(events) == 2
    event_names = [e.__class__.__name__ for e in events]
    assert "PlayerRatingComputed" in event_names
    assert "PlayerMilestoneReached" in event_names

    milestone = next(e for e in events if e.__class__.__name__ == "PlayerMilestoneReached")
    assert milestone.payload["milestone_type"] == "ELITE_RATING"
    assert milestone.payload["value"] >= ELITE_RATING_THRESHOLD
    assert milestone.payload["achieved_at"] == fixed_time.isoformat()


def test_domain_service_no_milestone_below_threshold():
    """Rating < 80.0 must emit only PlayerRatingComputed."""
    service = RatingComputationService()
    fixed_time = datetime(2026, 2, 1, 12, 0, 0)
    stats = [
        PlayerStats(
            player_external_id="pl-987",
            team_external_id="team-home",
            points=10, rebounds=5, assists=2, turnovers=1,
        ),
    ]

    rating = service.compute_and_evaluate(
        player_external_id=ExternalId("pl-987"),
        season_code=SeasonCode("2025-2026"),
        stats=stats,
        rating_version=RatingVersion("v1.0"),
        calculated_at=fixed_time,
    )

    events = rating.collect_events()
    assert len(events) == 1
    assert events[0].__class__.__name__ == "PlayerRatingComputed"


def test_domain_service_rating_reproducibility():
    """Two identical calls produce the same rating value."""
    service = RatingComputationService()
    fixed_time = datetime(2026, 2, 1, 12, 0, 0)
    stats = [
        PlayerStats(
            player_external_id="pl-987",
            team_external_id="team-home",
            points=20, rebounds=10, assists=5, turnovers=2,
        ),
        PlayerStats(
            player_external_id="pl-987",
            team_external_id="team-home",
            points=25, rebounds=8, assists=6, turnovers=3,
        ),
    ]

    rating1 = service.compute_and_evaluate(
        player_external_id=ExternalId("pl-987"),
        season_code=SeasonCode("2025-2026"),
        stats=stats,
        rating_version=RatingVersion("v1.0"),
        calculated_at=fixed_time,
    )
    rating2 = service.compute_and_evaluate(
        player_external_id=ExternalId("pl-987"),
        season_code=SeasonCode("2025-2026"),
        stats=stats,
        rating_version=RatingVersion("v1.0"),
        calculated_at=fixed_time,
    )

    assert rating1.rating_value.value == rating2.rating_value.value
    assert rating1.calculated_at == rating2.calculated_at


def _stat(points: int, day: int) -> PlayerStats:
    return PlayerStats(
        player_external_id="pl-987",
        team_external_id="team-home",
        points=points,
        rebounds=5,
        assists=2,
        turnovers=1,
        played_at=datetime(2026, 2, day, 18, 30),
    )


def test_window_all_differs_from_last_5_when_data_requires():
    service = RatingComputationService()
    stats = [_stat(points=10 + i, day=1 + i) for i in range(12)]
    fixed_time = datetime(2026, 2, 20, 12, 0, 0)

    all_rating = service.compute_and_evaluate(
        ExternalId("pl-987"), SeasonCode("2025-2026"), stats,
        RatingVersion("v1.0"), fixed_time, window="all",
    )
    last_5 = service.compute_and_evaluate(
        ExternalId("pl-987"), SeasonCode("2025-2026"), stats,
        RatingVersion("v1.0"), fixed_time, window="last_5",
    )
    assert all_rating.rating_value.value != last_5.rating_value.value


def test_window_last_5_differs_from_last_10_when_data_requires():
    service = RatingComputationService()
    stats = [_stat(points=10 + i, day=1 + i) for i in range(12)]
    fixed_time = datetime(2026, 2, 20, 12, 0, 0)

    last_5 = service.compute_and_evaluate(
        ExternalId("pl-987"), SeasonCode("2025-2026"), stats,
        RatingVersion("v1.0"), fixed_time, window="last_5",
    )
    last_10 = service.compute_and_evaluate(
        ExternalId("pl-987"), SeasonCode("2025-2026"), stats,
        RatingVersion("v1.0"), fixed_time, window="last_10",
    )
    assert last_5.rating_value.value != last_10.rating_value.value


def test_window_uses_most_recent_stats_by_played_at_regardless_of_input_order():
    """last_5 must always mean the 5 most recent by played_at, not by input order."""
    service = RatingComputationService()
    stats = [_stat(points=1 + i, day=1 + i) for i in range(7)]
    shuffled = list(reversed(stats))
    fixed_time = datetime(2026, 2, 20, 12, 0, 0)

    rating = service.compute_and_evaluate(
        ExternalId("pl-987"), SeasonCode("2025-2026"), shuffled,
        RatingVersion("v1.0"), fixed_time, window="last_5",
    )
    # Expected: only the 5 most recent (points 3..7) contribute.
    most_recent = stats[-5:]
    expected = round(
        (sum(s.points for s in most_recent)
         + sum(s.rebounds for s in most_recent) * 1.2
         + sum(s.assists for s in most_recent) * 1.5
         - sum(s.turnovers for s in most_recent) * 0.8) / 5,
        2,
    )
    assert rating.rating_value.value == expected


def test_window_with_fewer_stats_than_limit_uses_all_available():
    service = RatingComputationService()
    stats = [_stat(points=10 + i, day=1 + i) for i in range(3)]
    fixed_time = datetime(2026, 2, 20, 12, 0, 0)

    all_rating = service.compute_and_evaluate(
        ExternalId("pl-987"), SeasonCode("2025-2026"), stats,
        RatingVersion("v1.0"), fixed_time, window="all",
    )
    last_5 = service.compute_and_evaluate(
        ExternalId("pl-987"), SeasonCode("2025-2026"), stats,
        RatingVersion("v1.0"), fixed_time, window="last_5",
    )
    assert last_5.rating_value.value == all_rating.rating_value.value


def test_window_result_is_deterministic():
    service = RatingComputationService()
    stats = [_stat(points=10 + i, day=1 + i) for i in range(12)]
    fixed_time = datetime(2026, 2, 20, 12, 0, 0)

    rating1 = service.compute_and_evaluate(
        ExternalId("pl-987"), SeasonCode("2025-2026"), stats,
        RatingVersion("v1.0"), fixed_time, window="last_10",
    )
    rating2 = service.compute_and_evaluate(
        ExternalId("pl-987"), SeasonCode("2025-2026"), stats,
        RatingVersion("v1.0"), fixed_time, window="last_10",
    )
    assert rating1.rating_value.value == rating2.rating_value.value


def test_service_raises_without_stats_and_emits_no_events():
    service = RatingComputationService()
    with pytest.raises(InvalidRatingCalculation):
        service.compute_and_evaluate(
            ExternalId("pl-987"), SeasonCode("2025-2026"), [],
            RatingVersion("v1.0"), datetime(2026, 2, 20, 12, 0, 0),
        )
