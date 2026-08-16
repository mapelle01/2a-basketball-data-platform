import pytest
from datetime import datetime

from feb_score.domain.statistics.model import PlayerStats

@pytest.fixture
def db(backend):
    return backend.make_db()

@pytest.fixture
def stats_repo(backend, db):
    if backend.name == "in-memory":
        from feb_score.application.repositories.in_memory import InMemoryMatchStatsRepository
        return InMemoryMatchStatsRepository()
    return backend.repo(db, "stats")


def test_season_player_aggregates(stats_repo):
    # Setup: 3 matches, 2 players
    # Player 1 plays in match 1, 2, 3
    # Player 2 plays in match 1, 2
    
    ps1_m1 = PlayerStats(
        player_external_id="P1", team_external_id="T1", points=10, rebounds=5, assists=2,
        steals=1, blocks=0, turnovers=3, minutes=20.5, played_at=datetime.utcnow()
    )
    ps2_m1 = PlayerStats(
        player_external_id="P2", team_external_id="T2", points=15, rebounds=3, assists=8,
        steals=2, blocks=1, turnovers=1, minutes=30.0, played_at=datetime.utcnow()
    )
    
    ps1_m2 = PlayerStats(
        player_external_id="P1", team_external_id="T1", points=12, rebounds=6, assists=3,
        steals=0, blocks=1, turnovers=2, minutes=22.0, played_at=datetime.utcnow()
    )
    ps2_m2 = PlayerStats(
        player_external_id="P2", team_external_id="T2", points=20, rebounds=4, assists=10,
        steals=3, blocks=0, turnovers=4, minutes=35.0, played_at=datetime.utcnow()
    )
    
    # Player 1 changes team in match 3
    ps1_m3 = PlayerStats(
        player_external_id="P1", team_external_id="T2", points=8, rebounds=4, assists=1,
        steals=2, blocks=0, turnovers=1, minutes=15.0, played_at=datetime.utcnow()
    )
    
    # Another season match
    ps1_m4_other = PlayerStats(
        player_external_id="P1", team_external_id="T1", points=30, rebounds=10, assists=5,
        steals=5, blocks=5, turnovers=5, minutes=40.0, played_at=datetime.utcnow()
    )
    
    stats_repo.save_player_stats("M1", "2025-2026", [ps1_m1, ps2_m1])
    stats_repo.save_player_stats("M2", "2025-2026", [ps1_m2, ps2_m2])
    stats_repo.save_player_stats("M3", "2025-2026", [ps1_m3])
    
    # Other season
    stats_repo.save_player_stats("M4", "2024-2025", [ps1_m4_other])
    
    # Fetch aggregates for 2025-2026
    aggregates = stats_repo.list_season_player_aggregates("2025-2026")
    aggr_list = list(aggregates)
    
    # Case 6: Determinism (ordered by player_external_id)
    assert len(aggr_list) == 2
    assert aggr_list[0].player_external_id == "P1"
    assert aggr_list[1].player_external_id == "P2"
    
    p1 = aggr_list[0]
    p2 = aggr_list[1]
    
    # Case 1 & 3: Player 1 (3 matches, different teams)
    assert p1.games_played == 3
    assert p1.points == 10 + 12 + 8
    assert p1.rebounds == 5 + 6 + 4
    assert p1.assists == 2 + 3 + 1
    assert p1.steals == 1 + 0 + 2
    assert p1.blocks == 0 + 1 + 0
    assert p1.turnovers == 3 + 2 + 1
    assert p1.minutes == 20.5 + 22.0 + 15.0
    assert p1.season_code == "2025-2026"
    
    # Case 2: Player 2 (2 matches)
    assert p2.games_played == 2
    assert p2.points == 15 + 20
    assert p2.rebounds == 3 + 4
    assert p2.assists == 8 + 10
    
    # Case 4: Other season data is isolated
    aggr_other = list(stats_repo.list_season_player_aggregates("2024-2025"))
    assert len(aggr_other) == 1
    assert aggr_other[0].games_played == 1
    assert aggr_other[0].points == 30
