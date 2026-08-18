from datetime import datetime

import pytest

from feb_score.domain.errors import InvalidRatingCalculation
from feb_score.domain.ratings.model import TeamRating, compute_power_ranking
from feb_score.domain.statistics.model import SeasonTeamStats


def _team_stats(
    *,
    team_id="team-a",
    gp=20,
    wins=12,
    pf=1600,
    pa=1500,
    fgm=600,
    fga=1200,
    p3m=120,
    p3a=350,
    ftm=200,
    fta=260,
    to=250,
    reb=700,
) -> SeasonTeamStats:
    return SeasonTeamStats(
        team_external_id=team_id,
        season_code="2025-2026",
        games_played=gp,
        wins=wins,
        losses=gp - wins,
        points_for=pf,
        points_against=pa,
        field_goals_made=fgm,
        field_goals_attempted=fga,
        three_points_made=p3m,
        three_points_attempted=p3a,
        free_throws_made=ftm,
        free_throws_attempted=fta,
        turnovers=to,
        rebounds=reb,
    )


def test_compute_team_rating_basic():
    stats = _team_stats()
    rating = TeamRating.compute(stats, calculated_at=datetime(2026, 3, 1))

    assert rating.team_external_id == "team-a"
    assert rating.season_code == "2025-2026"
    assert rating.rating_version == "v1.0"
    assert 0 <= rating.rating_value <= 100
    assert 0 <= rating.offensive_rating <= 100
    assert 0 <= rating.defensive_rating <= 100
    assert 0 <= rating.net_rating <= 100
    assert 0 <= rating.win_factor <= 100
    assert rating.games_played == 20


def test_winning_team_rates_higher_than_losing_team():
    winner = _team_stats(team_id="winner", wins=18, pf=1700, pa=1400)
    loser = _team_stats(team_id="loser", wins=4, pf=1300, pa=1700)
    t = datetime(2026, 3, 1)

    r_win = TeamRating.compute(winner, calculated_at=t)
    r_lose = TeamRating.compute(loser, calculated_at=t)

    assert r_win.rating_value > r_lose.rating_value


def test_offensive_team_has_higher_offensive_rating():
    offensive = _team_stats(team_id="off", pf=1800, pa=1600, fgm=700, fga=1200)
    defensive = _team_stats(team_id="def", pf=1400, pa=1300, fgm=500, fga=1200)
    t = datetime(2026, 3, 1)

    r_off = TeamRating.compute(offensive, calculated_at=t)
    r_def = TeamRating.compute(defensive, calculated_at=t)

    assert r_off.offensive_rating > r_def.offensive_rating


def test_team_rating_zero_games_raises():
    stats = SeasonTeamStats(
        team_external_id="team-a",
        season_code="2025-2026",
        games_played=0,
        wins=0,
        losses=0,
        points_for=0,
        points_against=0,
        field_goals_made=0,
        field_goals_attempted=0,
        three_points_made=0,
        three_points_attempted=0,
        free_throws_made=0,
        free_throws_attempted=0,
        turnovers=0,
        rebounds=0,
    )
    with pytest.raises(InvalidRatingCalculation):
        TeamRating.compute(stats)


def test_team_rating_deterministic():
    stats = _team_stats()
    t = datetime(2026, 3, 1)
    r1 = TeamRating.compute(stats, calculated_at=t)
    r2 = TeamRating.compute(stats, calculated_at=t)
    assert r1.rating_value == r2.rating_value
    assert r1.offensive_rating == r2.offensive_rating
    assert r1.defensive_rating == r2.defensive_rating


def test_team_rating_to_dict():
    stats = _team_stats()
    rating = TeamRating.compute(stats, calculated_at=datetime(2026, 3, 1))
    d = rating.to_dict()
    assert d["team_external_id"] == "team-a"
    assert d["rating_version"] == "v1.0"
    assert isinstance(d["rating_value"], float)
    assert isinstance(d["games_played"], int)


# ---------------------------------------------------------------- PowerRanking

def test_power_ranking_ordered_by_rating():
    t = datetime(2026, 3, 1)
    strong = TeamRating.compute(_team_stats(team_id="strong", wins=18, pf=1800, pa=1400), calculated_at=t)
    mid = TeamRating.compute(_team_stats(team_id="mid", wins=10, pf=1500, pa=1500), calculated_at=t)
    weak = TeamRating.compute(_team_stats(team_id="weak", wins=3, pf=1300, pa=1700), calculated_at=t)

    ranking = compute_power_ranking([weak, strong, mid])

    assert len(ranking) == 3
    assert ranking[0].rank == 1
    assert ranking[0].team_external_id == "strong"
    assert ranking[1].rank == 2
    assert ranking[2].rank == 3
    assert ranking[2].team_external_id == "weak"


def test_power_ranking_with_limit():
    t = datetime(2026, 3, 1)
    teams = [
        TeamRating.compute(_team_stats(team_id=f"t{i}", wins=10 + i), calculated_at=t)
        for i in range(5)
    ]
    ranking = compute_power_ranking(teams, limit=3)
    assert len(ranking) == 3
    assert ranking[0].rank == 1


def test_power_ranking_tiebreaker_by_id():
    t = datetime(2026, 3, 1)
    a = TeamRating.compute(_team_stats(team_id="aaa"), calculated_at=t)
    b = TeamRating.compute(_team_stats(team_id="bbb"), calculated_at=t)
    # Same stats → same rating → alphabetical tiebreaker
    assert a.rating_value == b.rating_value
    ranking = compute_power_ranking([b, a])
    assert ranking[0].team_external_id == "aaa"
    assert ranking[1].team_external_id == "bbb"


def test_power_ranking_entry_to_dict():
    t = datetime(2026, 3, 1)
    rating = TeamRating.compute(_team_stats(), calculated_at=t)
    ranking = compute_power_ranking([rating])
    d = ranking[0].to_dict()
    assert d["rank"] == 1
    assert "offensive_rating" in d
