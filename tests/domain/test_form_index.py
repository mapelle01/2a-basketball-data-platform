from datetime import datetime

import pytest

from feb_score.domain.errors import InvalidRatingCalculation
from feb_score.domain.ratings.model import FormIndex
from feb_score.domain.statistics.model import PlayerStats


def _pstat(pts: int, day: int, reb: int = 5, ast: int = 3, stl: int = 1, blk: int = 0, to: int = 2) -> PlayerStats:
    return PlayerStats(
        player_external_id="pl-1",
        team_external_id="team-a",
        points=pts,
        rebounds=reb,
        assists=ast,
        steals=stl,
        blocks=blk,
        turnovers=to,
        played_at=datetime(2026, 2, day, 18, 30),
    )


# ---------------------------------------------------------------- Player FormIndex

def test_player_form_rising():
    # Season: low-scoring early, high-scoring recently
    stats = [_pstat(pts=8, day=i) for i in range(1, 11)]
    stats += [_pstat(pts=25, day=i) for i in range(11, 16)]

    fi = FormIndex.compute_player("pl-1", "2025-2026", stats, window=5)

    assert fi.entity_type == "player"
    assert fi.trend == "rising"
    assert fi.form_index > 1.05
    assert fi.window == 5


def test_player_form_falling():
    # Season: high-scoring early, low-scoring recently
    stats = [_pstat(pts=25, day=i) for i in range(1, 11)]
    stats += [_pstat(pts=5, day=i) for i in range(11, 16)]

    fi = FormIndex.compute_player("pl-1", "2025-2026", stats, window=5)

    assert fi.trend == "falling"
    assert fi.form_index < 0.95


def test_player_form_stable():
    # Consistent scoring
    stats = [_pstat(pts=15, day=i) for i in range(1, 16)]

    fi = FormIndex.compute_player("pl-1", "2025-2026", stats, window=5)

    assert fi.trend == "stable"
    assert 0.95 <= fi.form_index <= 1.05


def test_player_form_requires_minimum_games():
    stats = [_pstat(pts=10, day=1)]
    with pytest.raises(InvalidRatingCalculation):
        FormIndex.compute_player("pl-1", "2025-2026", stats, window=5)


def test_player_form_window_smaller_than_data():
    stats = [_pstat(pts=10, day=i) for i in range(1, 4)]
    fi = FormIndex.compute_player("pl-1", "2025-2026", stats, window=5)
    # Only 3 games, window=5 → uses all 3 as recent
    assert fi.window == 3


def test_player_form_deterministic():
    stats = [_pstat(pts=10 + i, day=i) for i in range(1, 11)]
    fi1 = FormIndex.compute_player("pl-1", "2025-2026", stats, window=5)
    fi2 = FormIndex.compute_player("pl-1", "2025-2026", stats, window=5)
    assert fi1.form_index == fi2.form_index
    assert fi1.trend == fi2.trend


def test_player_form_respects_played_at_order():
    # Shuffle input order — should still use most recent by played_at
    stats = [_pstat(pts=5, day=i) for i in range(1, 6)]
    stats += [_pstat(pts=30, day=i) for i in range(6, 11)]
    shuffled = list(reversed(stats))

    fi = FormIndex.compute_player("pl-1", "2025-2026", shuffled, window=5)
    assert fi.trend == "rising"


def test_player_form_to_dict():
    stats = [_pstat(pts=15, day=i) for i in range(1, 11)]
    fi = FormIndex.compute_player("pl-1", "2025-2026", stats, window=5)
    d = fi.to_dict()
    assert d["entity_external_id"] == "pl-1"
    assert d["entity_type"] == "player"
    assert "form_index" in d
    assert "trend" in d


# ---------------------------------------------------------------- Team FormIndex

def test_team_form_rising():
    # Lost early, winning recently
    diffs = [-5, -10, -3, -8, -2, 5, 10, 8, 12, 15]
    fi = FormIndex.compute_team("team-a", "2025-2026", diffs, window=5)
    assert fi.entity_type == "team"
    assert fi.trend == "rising"


def test_team_form_falling():
    diffs = [15, 12, 10, 8, 5, -2, -5, -10, -8, -12]
    fi = FormIndex.compute_team("team-a", "2025-2026", diffs, window=5)
    assert fi.trend == "falling"


def test_team_form_stable():
    diffs = [5, 3, 4, 6, 5, 4, 5, 3, 6, 4]
    fi = FormIndex.compute_team("team-a", "2025-2026", diffs, window=5)
    assert fi.trend == "stable"


def test_team_form_requires_minimum_rounds():
    with pytest.raises(InvalidRatingCalculation):
        FormIndex.compute_team("team-a", "2025-2026", [5], window=5)


def test_team_form_to_dict():
    diffs = [5, 3, 4, 6, 5, 4, 5, 3, 6, 4]
    fi = FormIndex.compute_team("team-a", "2025-2026", diffs, window=5)
    d = fi.to_dict()
    assert d["entity_type"] == "team"
    assert d["window"] == 5
