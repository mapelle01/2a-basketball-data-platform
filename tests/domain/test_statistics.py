import pytest

from feb_score.domain.statistics.model import PlayerStats, TeamStats


def test_player_stats_validation():
    stats = PlayerStats(
        player_external_id="pl-1",
        team_external_id="team-home",
        points=15,
        rebounds=7,
        assists=4,
        steals=1,
        blocks=2,
        turnovers=3,
        minutes=28.5,
    )
    assert stats.to_dict()["points"] == 15

    with pytest.raises(ValueError):
        PlayerStats(
            player_external_id="pl-1",
            team_external_id="team-home",
            points=-1,
            rebounds=5,
            assists=2,
        )

    with pytest.raises(ValueError):
        PlayerStats(
            player_external_id="pl-1",
            team_external_id="team-home",
            points=10,
            rebounds=5,
            assists=2,
            minutes=-5.0,
        )


def test_team_stats_validation():
    stats = TeamStats(
        team_external_id="team-home",
        points_for=80,
        points_against=75,
        field_goals_made=30,
        field_goals_attempted=60,
        three_points_made=8,
        three_points_attempted=20,
        free_throws_made=12,
        free_throws_attempted=16,
        turnovers=10,
        rebounds=38,
    )
    assert stats.to_dict()["points_for"] == 80

    with pytest.raises(ValueError):
        TeamStats(
            team_external_id="team-home",
            points_for=80,
            points_against=75,
            field_goals_made=30,
            field_goals_attempted=20,
            three_points_made=8,
            three_points_attempted=20,
            free_throws_made=12,
            free_throws_attempted=16,
            turnovers=10,
            rebounds=38,
        )

    with pytest.raises(ValueError):
        TeamStats(
            team_external_id="team-home",
            points_for=80,
            points_against=75,
            field_goals_made=30,
            field_goals_attempted=60,
            three_points_made=8,
            three_points_attempted=5,
            free_throws_made=12,
            free_throws_attempted=16,
            turnovers=10,
            rebounds=38,
        )

    with pytest.raises(ValueError):
        TeamStats(
            team_external_id="team-home",
            points_for=80,
            points_against=75,
            field_goals_made=30,
            field_goals_attempted=60,
            three_points_made=8,
            three_points_attempted=20,
            free_throws_made=20,
            free_throws_attempted=16,
            turnovers=10,
            rebounds=38,
        )

    with pytest.raises(ValueError):
        TeamStats(
            team_external_id="team-home",
            points_for=-1,
            points_against=75,
            field_goals_made=30,
            field_goals_attempted=60,
            three_points_made=8,
            three_points_attempted=20,
            free_throws_made=12,
            free_throws_attempted=16,
            turnovers=10,
            rebounds=38,
        )
