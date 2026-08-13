"""FASE 9 — Performance: rough measurements (no premature optimization).

We only measure the main persistence paths to catch pathological slowness.
Bounds are deliberately generous; results are informational.
"""

import time

from feb_score.application.commands.commands import (
    ComputePlayerRatingCommand,
    GenerateLeaderboardCommand,
    GenerateStandingSnapshotCommand,
)
from feb_score.application.use_cases.handlers import (
    ComputePlayerRatingHandler,
    GenerateLeaderboardHandler,
    GenerateStandingSnapshotHandler,
)
from feb_score.infrastructure.persistence.connection import SqliteDatabase
from feb_score.infrastructure.persistence.repositories import (
    SqliteLeaderboardRepository,
    SqliteMatchRepository,
    SqlitePlayerRepository,
    SqliteRatingRepository,
    SqliteStandingRepository,
)
from feb_score.domain.value_objects import ExternalId

from sqlite_helpers import cmd, finalized_match, make_player, run


def _elapsed(fn, repeat=1):
    start = time.perf_counter()
    for _ in range(repeat):
        fn()
    return time.perf_counter() - start


def test_db_creation_and_save_load_are_reasonable(tmp_path):
    path = str(tmp_path / "perf.db")

    def create():
        db = SqliteDatabase(path)
        db.migrate()

    def save_load_match():
        db = SqliteDatabase(path)
        match = finalized_match()
        match.external_id = ExternalId(f"m-perf-{save_load_match.i}")
        match.match_id = __import__("feb_score.domain.value_objects", fromlist=["MatchId"]).MatchId(str(__import__("uuid").uuid4()))
        match.clear_events()
        SqliteMatchRepository(db).save(match)
        SqliteMatchRepository(db).get_by_external_id(match.external_id)
        save_load_match.i += 1

    save_load_match.i = 0

    def save_load_player():
        db = SqliteDatabase(path)
        SqlitePlayerRepository(db).save(make_player())
        SqlitePlayerRepository(db).get_by_external_id(ExternalId("pl-987"))

    create_time = _elapsed(create)
    match_time = _elapsed(save_load_match, repeat=50)
    player_time = _elapsed(save_load_player, repeat=50)

    # generous sanity bounds: nothing here should take more than a few seconds total
    assert create_time < 2.0
    assert match_time < 5.0
    assert player_time < 5.0

    print(f"\n[perf] db create: {create_time:.3f}s | save/load match x50: {match_time:.3f}s "
          f"| save/load player x50: {player_time:.3f}s")


def test_compute_rating_leaderboard_standing_are_reasonable(tmp_path):
    path = str(tmp_path / "perf2.db")
    db = SqliteDatabase(path)
    db.migrate()
    match_repo = SqliteMatchRepository(db)
    for i in range(20):
        match = finalized_match()
        match.external_id = ExternalId(f"m-{i}")
        match.match_id = __import__("feb_score.domain.value_objects", fromlist=["MatchId"]).MatchId(str(__import__("uuid").uuid4()))
        match.clear_events()
        match_repo.save(match)

    def compute_rating():
        run(db, ComputePlayerRatingHandler(match_repo, SqliteRatingRepository(db)),
            ComputePlayerRatingCommand(**cmd({
                "player_external_id": "pl-1", "season_code": "2025-2026", "rating_version": "v1.0",
                "competition_id": "feb-comp",
            })))

    def leaderboard():
        run(db, GenerateLeaderboardHandler(match_repo, SqliteLeaderboardRepository(db)),
            GenerateLeaderboardCommand(**cmd({
                "season_code": "2025-2026", "category": "points_per_game", "min_games": 0, "top_n": 10,
                "competition_id": "feb-comp",
            })))

    def standing():
        run(db, GenerateStandingSnapshotHandler(SqliteStandingRepository(db), match_repo),
            GenerateStandingSnapshotCommand(**cmd({
                "competition_id": "feb-comp", "season_code": "2025-2026",
                "as_of": "2026-02-01T23:59:59Z", "rules_version": "rules-v1",
            })))

    rating_time = _elapsed(compute_rating)
    leaderboard_time = _elapsed(leaderboard)
    standing_time = _elapsed(standing)

    assert rating_time < 5.0
    assert leaderboard_time < 5.0
    assert standing_time < 5.0

    print(f"[perf] compute rating: {rating_time:.3f}s | leaderboard: {leaderboard_time:.3f}s "
          f"| standing snapshot: {standing_time:.3f}s")