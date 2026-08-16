"""FASE 24 — exploration production validator tests (PostgreSQL).

``validate_season_exploration_production.py`` is the read-only gate for the
match/player exploration surface (FASE 24.1-24.4). These tests prove it gates:
a production-shaped dataset (364 matches / 26 rounds x 14 / 28 teams / players
with season registrations) must PASS every block, while corrupted data must be
reported as FAIL. All checks run through the real validator functions.
"""

from __future__ import annotations

import json
import random
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from feb_score.application.persistence.serialization import match_to_dict, player_to_dict, team_to_dict
from feb_score.domain.match.model import Match
from feb_score.domain.player.model import Player
from feb_score.domain.statistics.model import PlayerStats, TeamStats
from feb_score.domain.team.model import Team
from feb_score.domain.value_objects import (
    CompetitionId,
    ExternalId,
    MatchId,
    PlayerId,
    SeasonCode,
    TeamId,
)
from feb_score.infrastructure.persistence.postgres.repositories import (
    PgMatchStatsRepository,
    PgPlayerRepository,
    PgTeamRepository,
)

from validate_season_exploration_production import SEASON, run_validations, validate_production

TEAMS = [f"TEAM-{i:02d}" for i in range(1, 29)]
PLAYERS = [f"PL-{i:03d}" for i in range(1, 31)]  # 30 players keep the test fast


def _seed_full(db) -> None:
    """Deterministic production-equivalent dataset on an isolated PG schema."""
    rng = random.Random(2304)
    stats_repo = PgMatchStatsRepository(db)
    player_repo = PgPlayerRepository(db)
    team_repo = PgTeamRepository(db)

    for i, tid in enumerate(TEAMS):
        team_repo.save(Team(external_id=ExternalId(tid), team_id=TeamId(str(uuid4())),
                            name=f"Club {tid}"))
    for i, pid in enumerate(PLAYERS):
        player = Player(external_id=ExternalId(pid), player_id=PlayerId(str(uuid4())),
                        name=f"Jugador {pid}")
        player.register_for_team(TEAMS[i % 28], SeasonCode(SEASON), dorsal=(i % 20) + 1)
        player_repo.save(player)

    player_team = {p: TEAMS[i % 28] for i, p in enumerate(PLAYERS)}

    with db.connect() as conn:
        match_id = 0
        for rnd in range(1, 27):
            teams = TEAMS[:]
            rng.shuffle(teams)
            for g in range(14):
                match_id += 1
                mid = f"M{match_id}"
                uuid = str(uuid4())
                home, away = teams[2 * g], teams[2 * g + 1]
                home_score = rng.randint(65, 105)
                away_score = rng.randint(60, 110)
                while away_score == home_score:
                    away_score = rng.randint(60, 110)
                match = Match(
                    external_id=ExternalId(mid), match_id=MatchId(uuid),
                    competition_id=CompetitionId("segunda-feb"),
                    season_code=SeasonCode(SEASON), round_number=rnd,
                    home_team_id=ExternalId(home), away_team_id=ExternalId(away),
                    scheduled_at=datetime(2026, 2, 1, 18, 30),
                )
                conn.execute(
                    "INSERT INTO matches (match_id, external_id, competition_id,"
                    " season_code, status, version, data)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (uuid, mid, "segunda-feb", SEASON, "FINALIZED", 1, json.dumps(match_to_dict(match))),
                )
                for team, pf, pa in ((home, home_score, away_score),
                                     (away, away_score, home_score)):
                    fgm = rng.randint(22, 38)
                    fga = fgm + rng.randint(15, 30)
                    tpm = rng.randint(5, 15)
                    tpa = tpm + rng.randint(8, 18)
                    ftm = rng.randint(8, 22)
                    fta = ftm + rng.randint(3, 10)
                    stats_repo.save_team_stats(mid, SEASON, [
                        TeamStats(
                            team_external_id=team, points_for=pf, points_against=pa,
                            field_goals_made=fgm, field_goals_attempted=fga,
                            three_points_made=tpm, three_points_attempted=tpa,
                            free_throws_made=ftm, free_throws_attempted=fta,
                            turnovers=rng.randint(8, 18), rebounds=rng.randint(28, 45),
                        )
                    ])
                for team in (home, away):
                    squad = [p for p in PLAYERS if player_team[p] == team]
                    rng.shuffle(squad)
                    for p in squad[:11]:
                        stats_repo.save_player_stats(mid, SEASON, [
                            PlayerStats(
                                player_external_id=p, team_external_id=team,
                                points=rng.randint(0, 30), rebounds=rng.randint(0, 12),
                                assists=rng.randint(0, 9), steals=rng.randint(0, 5),
                                blocks=rng.randint(0, 4), turnovers=rng.randint(0, 6),
                                minutes=rng.choice([18.0, 22.0, 25.0, 28.0, 30.0, 32.0, 35.0]),
                            )
                        ])
        # stats-only player with NO official name source -> catalog record with
        # NULL name (FASE 24.1 backfill shape): derived identity, not searchable
        _catalog_player = Player(external_id=ExternalId("PL-099"),
                                 player_id=PlayerId(str(uuid4())), name=None)
        player_repo.upsert_catalog(ExternalId("PL-099"), _catalog_player.player_id,
                                   name=None, data=json.dumps(player_to_dict(_catalog_player)))
        stats_repo.save_player_stats("M1", SEASON, [
            PlayerStats(player_external_id="PL-099", team_external_id="TEAM-01",
                        points=5, rebounds=2, assists=1, steals=0, blocks=0,
                        turnovers=1, minutes=12.0)
        ])
        # season-isolation contamination row (other season -> must be ignored)
        data = {
            "external_id": "M999", "match_id": "M999", "competition_id": "segunda-feb",
            "season_code": "2024-2025", "round_number": 1,
            "home_team_id": "TEAM-01", "away_team_id": "TEAM-02",
            "status": "FINALIZED", "version": 1,
        }
        conn.execute(
            "INSERT INTO matches (match_id, external_id, competition_id,"
            " season_code, status, version, data)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s)",
            ("M999", "M999", "segunda-feb", "2024-2025", "FINALIZED", 1, json.dumps(data)),
        )


def test_validator_passes_on_production_shaped_data(pg_db):
    _seed_full(pg_db)
    code, failures = run_validations(pg_db, SEASON)
    assert code == 0
    assert failures == []


def test_validator_reports_broken_boxscore(pg_db):
    _seed_full(pg_db)
    with pg_db.connect() as conn:
        # home team scores one more point than away recorded -> points_for != points_against
        # (the boxscore read model deserializes the `data` JSONB blob, not the columns)
        conn.execute(
            "UPDATE match_team_stats SET data = jsonb_set("
            "  data, '{points_for}', to_jsonb((data->>'points_for')::int + 1))"
            " WHERE season_code = %s AND match_external_id = 'M1'"
            " AND team_external_id = (SELECT data->>'home_team_id' FROM matches"
            "   WHERE external_id = 'M1' LIMIT 1)",
            (SEASON,),
        )
    code, failures = run_validations(pg_db, SEASON)
    assert code != 0
    assert any("points_for" in f or "points_against" in f for f in failures)


def test_validator_reports_evolution_round_gap(pg_db):
    _seed_full(pg_db)
    with pg_db.connect() as conn:
        # strip TEAM-01's stats from its round-26 matches -> evolution 1..25 gap
        conn.execute(
            "DELETE FROM match_team_stats WHERE season_code = %s"
            " AND team_external_id = 'TEAM-01'"
            " AND match_external_id IN ("
            "  SELECT external_id FROM matches WHERE season_code = %s"
            "  AND competition_id = 'segunda-feb'"
            "  AND (data->>'round_number')::int = 26"
            "  AND (data->>'home_team_id' = 'TEAM-01' OR data->>'away_team_id' = 'TEAM-01'))",
            (SEASON, SEASON),
        )
    code, failures = run_validations(pg_db, SEASON)
    assert code != 0
    assert any("evolution" in f or "rounds" in f for f in failures)


def test_validator_reports_player_name_drift(pg_db):
    _seed_full(pg_db)
    with pg_db.connect() as conn:
        # desync the players.name column from the stored data blob -> profile mismatch
        conn.execute(
            "UPDATE players SET name = 'Jugador corrupto' WHERE external_id = 'PL-001'",
        )
    code, failures = run_validations(pg_db, SEASON)
    assert code != 0
    assert any("profile name" in f for f in failures)


def test_validator_reports_catalog_duplicate_external_id(pg_db):
    """FASE 24.1 — duplicate external_ids break canonical identity."""
    _seed_full(pg_db)
    with pg_db.connect() as conn:
        # the schema normally forbids duplicates via a unique constraint; drop it
        # so we can prove the validator still guards the invariant
        conn.execute("ALTER TABLE teams DROP CONSTRAINT teams_external_id_key")
        _dup = Team(external_id=ExternalId("TEAM-01"), team_id=TeamId(str(uuid4())),
                    name="Club duplicado")
        conn.execute(
            "INSERT INTO teams (team_id, external_id, name, data)"
            " VALUES (%s, %s, %s, %s)",
            (str(_dup.team_id), str(_dup.external_id), _dup.name,
             json.dumps(team_to_dict(_dup))),
        )
    code, failures = run_validations(pg_db, SEASON)
    assert code != 0
    assert any("duplicates present" in f for f in failures)


def test_validator_reports_player_without_catalog_record(pg_db):
    """FASE 24.1 — a stats entity with no catalog record means backfill is pending."""
    _seed_full(pg_db)
    with pg_db.connect() as conn:
        conn.execute("DELETE FROM players WHERE external_id = 'PL-005'")
    code, failures = run_validations(pg_db, SEASON)
    assert code != 0
    assert any("no catalog record" in f for f in failures)


def test_validator_null_name_entities_pass_and_are_skipped(pg_db):
    """FASE 24.1 — entities with no official name (name NULL) are allowed and
    simply skipped by name search; the validator must still PASS."""
    _seed_full(pg_db)
    with pg_db.connect() as conn:
        conn.execute("UPDATE teams SET name = NULL WHERE external_id = 'TEAM-01'")
    code, failures = run_validations(pg_db, SEASON)
    assert code == 0
    assert failures == []


def test_validate_production_requires_dsn(monkeypatch):
    monkeypatch.delenv("FEB_SCORE_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert validate_production() == 1