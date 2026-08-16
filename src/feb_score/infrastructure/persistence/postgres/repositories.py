"""PostgreSQL repositories implementing the application repository interfaces.

Same contract as the SQLite repositories: aggregates are reconstructed via the
serialization module; normalized key columns serve lookups; optimistic
concurrency for ``matches`` is a version-checked ``UPDATE ... WHERE version``.

SQL-flavored differences (all behind the interface):
  * ``%s`` placeholders and ``dict_row`` rows (``row["data"]``);
  * ``INSERT ... ON CONFLICT ... DO UPDATE`` instead of ``INSERT OR REPLACE``;
  * ``matches`` version guard uses ``WHERE version = <expected>`` + rowcount;
  * psycopg exceptions are translated to the infrastructure taxonomy.
"""

from __future__ import annotations

import json
from typing import Iterable, List, Optional

from ....application.persistence.serialization import (
    competition_from_dict,
    competition_to_dict,
    correction_from_dict,
    correction_to_dict,
    leaderboard_from_dict,
    leaderboard_to_dict,
    match_from_dict,
    match_to_dict,
    player_from_dict,
    player_to_dict,
    publication_from_dict,
    publication_to_dict,
    rating_from_dict,
    rating_to_dict,
    standing_from_dict,
    standing_to_dict,
    team_from_dict,
    team_to_dict,
)
from ....application.repositories.interfaces import (
    CompetitionRepository,
    CorrectionRepository,
    IdempotencyRepository,
    LeaderboardRepository,
    MatchRepository,
    MatchStatsRepository,
    PlayerRepository,
    PublicationRepository,
    RatingRepository,
    StandingRepository,
    TeamRepository,
)
from ....domain.competition.model import Competition
from ....domain.correction.model import CorrectionProposal
from ....domain.leaderboard.model import Leaderboard
from ....domain.match.model import Match
from ....domain.player.model import Player
from ....domain.publication.model import Publication
from ....domain.ratings.model import PlayerRating
from ....domain.standings.model import StandingSnapshot
from ....domain.statistics.model import (
    PlayerLeaderboardMetric,
    PlayerStats,
    SeasonPlayerLeaderboardEntry,
    SeasonPlayerStats,
    SeasonTeamLeaderboardEntry,
    SeasonTeamStats,
    TeamLeaderboardMetric,
    TeamStats,
)
from ....domain.team.model import Team
from ....domain.value_objects import CompetitionId, ExternalId, LeaderboardId, SeasonCode
from ..errors import CorruptedRecordError, StaleVersionError
from .errors import translate_pg_error
from .connection import PgDatabase, pg_active_connection


_PLAYER_LEADERBOARD_ORDER = {
    PlayerLeaderboardMetric.POINTS: "points DESC, player_external_id ASC",
    PlayerLeaderboardMetric.REBOUNDS: "rebounds DESC, player_external_id ASC",
    PlayerLeaderboardMetric.ASSISTS: "assists DESC, player_external_id ASC",
    PlayerLeaderboardMetric.STEALS: "steals DESC, player_external_id ASC",
    PlayerLeaderboardMetric.BLOCKS: "blocks DESC, player_external_id ASC",
    PlayerLeaderboardMetric.TURNOVERS: "turnovers ASC, player_external_id ASC",
    PlayerLeaderboardMetric.GAMES_PLAYED: "games_played DESC, player_external_id ASC",
}

_TEAM_LEADERBOARD_ORDER = {
    TeamLeaderboardMetric.CLASSIFICATION:
        "wins DESC, losses ASC, (points_for - points_against) DESC, team_external_id ASC",
    TeamLeaderboardMetric.POINTS_FOR: "points_for DESC, team_external_id ASC",
    TeamLeaderboardMetric.POINT_DIFFERENCE:
        "(points_for - points_against) DESC, team_external_id ASC",
    TeamLeaderboardMetric.WIN_PERCENTAGE:
        "(CASE WHEN games_played > 0 THEN CAST(wins AS REAL) / games_played ELSE 0.0 END)"
        " DESC, wins DESC, team_external_id ASC",
}


class _PgRepoMixin:
    db: PgDatabase

    def _conn(self) -> tuple:
        active = pg_active_connection()
        if active is not None:
            return active, False
        return self.db.connect(), True

    def _fetch_data(self, table: str, where: str, params: tuple) -> Optional[str]:
        conn, owned = self._conn()
        try:
            row = conn.execute(f"SELECT data::text AS data FROM {table} WHERE {where}", params).fetchone()
            return row["data"] if row is not None else None
        finally:
            if owned:
                conn.close()

    def _deserialize(self, table: str, identity: str, data: str, converter) -> object:
        try:
            return converter(json.loads(data))
        except (json.JSONDecodeError, TypeError, ValueError, KeyError) as exc:
            raise CorruptedRecordError(f"{table} {identity} is corrupt: {exc}") from exc

    def _upsert(self, table: str, columns: str, values: tuple, conflict: str, update: str) -> None:
        conn, owned = self._conn()
        try:
            conn.execute(
                f"INSERT INTO {table} ({columns}) VALUES ({', '.join(['%s'] * len(values))})"
                f" ON CONFLICT ({conflict}) DO UPDATE SET {update}",
                values,
            )
        except Exception as exc:  # noqa: BLE001 - classify at the boundary
            raise translate_pg_error(exc) from exc
        finally:
            if owned:
                conn.close()


class PgMatchRepository(_PgRepoMixin, MatchRepository):
    def __init__(self, db: PgDatabase) -> None:
        self.db = db

    def save(self, match: Match) -> None:
        """Persist a match with the optimistic-concurrency guard (same contract
        as ``SqliteMatchRepository``): INSERT if new, version-checked UPDATE
        otherwise. A mismatch raises ``StaleVersionError`` and nothing is written."""
        conn, owned = self._conn()
        try:
            existing = conn.execute(
                "SELECT version FROM matches WHERE external_id = %s", (str(match.external_id),)
            ).fetchone()
            if existing is None:
                conn.execute(
                    "INSERT INTO matches"
                    " (match_id, external_id, competition_id, season_code, status, version, data)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)",
                    (
                        str(match.match_id),
                        str(match.external_id),
                        str(match.competition_id),
                        str(match.season_code),
                        str(match.status),
                        str(match.version),
                        json.dumps(match_to_dict(match)),
                    ),
                )
                return
            cursor = conn.execute(
                "UPDATE matches SET match_id = %s, competition_id = %s, season_code = %s,"
                " status = %s, version = %s, data = %s::jsonb"
                " WHERE external_id = %s AND version = %s",
                (
                    str(match.match_id),
                    str(match.competition_id),
                    str(match.season_code),
                    str(match.status),
                    str(match.version),
                    json.dumps(match_to_dict(match)),
                    str(match.external_id),
                    str(match.version - 1),
                ),
            )
            if cursor.rowcount == 0:
                raise StaleVersionError(
                    f"match {match.external_id}: stored version differs from expected "
                    f"{match.version - 1}; concurrent write detected"
                )
        except Exception as exc:  # noqa: BLE001 - classify at the boundary
            raise translate_pg_error(exc) from exc
        finally:
            if owned:
                conn.close()

    def get_by_external_id(self, external_id: ExternalId) -> Optional[Match]:
        data = self._fetch_data("matches", "external_id = %s", (str(external_id),))
        if data is None:
            return None
        return self._deserialize("matches", str(external_id), data, match_from_dict)

    def list_by_season(self, competition_id: CompetitionId, season_code: SeasonCode) -> Iterable[Match]:
        conn, owned = self._conn()
        try:
            rows = conn.execute(
                "SELECT data::text AS data FROM matches WHERE competition_id = %s AND season_code = %s",
                (str(competition_id), str(season_code)),
            ).fetchall()
            return [match_from_dict(json.loads(r["data"])) for r in rows]
        finally:
            if owned:
                conn.close()


class PgPlayerRepository(_PgRepoMixin, PlayerRepository):
    def __init__(self, db: PgDatabase) -> None:
        self.db = db

    def save(self, player: Player) -> None:
        self._upsert(
            "players", "player_id, external_id, name, data",
            (str(player.player_id), str(player.external_id), player.name, json.dumps(player_to_dict(player))),
            "external_id",
            "player_id = EXCLUDED.player_id, name = EXCLUDED.name, data = EXCLUDED.data",
        )

    def get_by_external_id(self, external_id: ExternalId) -> Optional[Player]:
        data = self._fetch_data("players", "external_id = %s", (str(external_id),))
        if data is None:
            return None
        return self._deserialize("players", str(external_id), data, player_from_dict)


class PgTeamRepository(_PgRepoMixin, TeamRepository):
    def __init__(self, db: PgDatabase) -> None:
        self.db = db

    def save(self, team: Team) -> None:
        self._upsert(
            "teams", "team_id, external_id, name, data",
            (str(team.team_id), str(team.external_id), team.name, json.dumps(team_to_dict(team))),
            "external_id",
            "team_id = EXCLUDED.team_id, name = EXCLUDED.name, data = EXCLUDED.data",
        )

    def get_by_external_id(self, external_id: ExternalId) -> Optional[Team]:
        data = self._fetch_data("teams", "external_id = %s", (str(external_id),))
        if data is None:
            return None
        return self._deserialize("teams", str(external_id), data, team_from_dict)


class PgCompetitionRepository(_PgRepoMixin, CompetitionRepository):
    def __init__(self, db: PgDatabase) -> None:
        self.db = db

    def save(self, competition: Competition) -> None:
        self._upsert(
            "competitions", "competition_id, external_id, name, data",
            (str(competition.competition_id), str(competition.external_id), competition.name,
             json.dumps(competition_to_dict(competition))),
            "external_id",
            "competition_id = EXCLUDED.competition_id, name = EXCLUDED.name, data = EXCLUDED.data",
        )

    def get_by_external_id(self, external_id: ExternalId) -> Optional[Competition]:
        data = self._fetch_data("competitions", "external_id = %s", (str(external_id),))
        if data is None:
            return None
        return self._deserialize("competitions", str(external_id), data, competition_from_dict)


class PgCorrectionRepository(_PgRepoMixin, CorrectionRepository):
    def __init__(self, db: PgDatabase) -> None:
        self.db = db

    def save(self, proposal: CorrectionProposal) -> None:
        self._upsert(
            "correction_proposals", "proposal_id, match_external_id, status, data",
            (str(proposal.proposal_id), str(proposal.match_external_id), proposal.status,
             json.dumps(correction_to_dict(proposal))),
            "proposal_id",
            "match_external_id = EXCLUDED.match_external_id, status = EXCLUDED.status, data = EXCLUDED.data",
        )

    def get_by_id(self, proposal_id: str) -> Optional[CorrectionProposal]:
        data = self._fetch_data("correction_proposals", "proposal_id = %s", (proposal_id,))
        if data is None:
            return None
        return self._deserialize("correction_proposals", proposal_id, data, correction_from_dict)


class PgStandingRepository(_PgRepoMixin, StandingRepository):
    def __init__(self, db: PgDatabase) -> None:
        self.db = db

    def save(self, standing_snapshot: StandingSnapshot) -> None:
        conn, owned = self._conn()
        try:
            conn.execute(
                "INSERT INTO standing_snapshots"
                " (snapshot_id, competition_id, season_code, generated_at, data)"
                " VALUES (%s, %s, %s, %s, %s::jsonb)",
                (str(standing_snapshot.snapshot_id), str(standing_snapshot.competition_id),
                 str(standing_snapshot.season_code), standing_snapshot.generated_at.isoformat(),
                 json.dumps(standing_to_dict(standing_snapshot))),
            )
        except Exception as exc:  # noqa: BLE001
            raise translate_pg_error(exc) from exc
        finally:
            if owned:
                conn.close()

    def list_all(self) -> List[StandingSnapshot]:
        conn, owned = self._conn()
        try:
            rows = conn.execute("SELECT data::text AS data FROM standing_snapshots ORDER BY generated_at").fetchall()
            return [standing_from_dict(json.loads(r["data"])) for r in rows]
        finally:
            if owned:
                conn.close()


class PgLeaderboardRepository(_PgRepoMixin, LeaderboardRepository):
    def __init__(self, db: PgDatabase) -> None:
        self.db = db

    def save(self, leaderboard: Leaderboard) -> None:
        self._upsert(
            "leaderboards", "leaderboard_id, season_code, category, generated_at, data",
            (str(leaderboard.leaderboard_id), str(leaderboard.season_code), leaderboard.category,
             leaderboard.generated_at.isoformat(), json.dumps(leaderboard_to_dict(leaderboard))),
            "leaderboard_id",
            "season_code = EXCLUDED.season_code, category = EXCLUDED.category,"
            " generated_at = EXCLUDED.generated_at, data = EXCLUDED.data",
        )

    def get_by_id(self, leaderboard_id: LeaderboardId) -> Optional[Leaderboard]:
        data = self._fetch_data("leaderboards", "leaderboard_id = %s", (str(leaderboard_id),))
        if data is None:
            return None
        return self._deserialize("leaderboards", str(leaderboard_id), data, leaderboard_from_dict)

    def list_all(self) -> List[Leaderboard]:
        conn, owned = self._conn()
        try:
            rows = conn.execute("SELECT data::text AS data FROM leaderboards ORDER BY generated_at").fetchall()
            return [leaderboard_from_dict(json.loads(r["data"])) for r in rows]
        finally:
            if owned:
                conn.close()


class PgRatingRepository(_PgRepoMixin, RatingRepository):
    def __init__(self, db: PgDatabase) -> None:
        self.db = db

    def save(self, player_rating: PlayerRating) -> None:
        conn, owned = self._conn()
        try:
            conn.execute(
                "INSERT INTO ratings"
                " (player_external_id, season_code, rating_version, calculated_at, data)"
                " VALUES (%s, %s, %s, %s, %s::jsonb)",
                (str(player_rating.player_external_id), str(player_rating.season_code),
                 str(player_rating.rating_version), player_rating.calculated_at.isoformat(),
                 json.dumps(rating_to_dict(player_rating))),
            )
        except Exception as exc:  # noqa: BLE001
            raise translate_pg_error(exc) from exc
        finally:
            if owned:
                conn.close()

    def list_all(self) -> List[PlayerRating]:
        conn, owned = self._conn()
        try:
            rows = conn.execute("SELECT data::text AS data FROM ratings ORDER BY rating_id").fetchall()
            return [rating_from_dict(json.loads(r["data"])) for r in rows]
        finally:
            if owned:
                conn.close()


class PgPublicationRepository(_PgRepoMixin, PublicationRepository):
    def __init__(self, db: PgDatabase) -> None:
        self.db = db

    def save(self, publication: Publication) -> None:
        # ON CONFLICT: publication_id is the command_id, so replaying the same
        # command overwrites the same publication (documented deviation).
        self._upsert(
            "publications", "publication_id, template_id, status, created_at, data",
            (str(publication.publication_id), publication.template_id, publication.status,
             publication.created_at.isoformat(), json.dumps(publication_to_dict(publication))),
            "publication_id",
            "template_id = EXCLUDED.template_id, status = EXCLUDED.status,"
            " created_at = EXCLUDED.created_at, data = EXCLUDED.data",
        )

    def list_all(self) -> List[Publication]:
        conn, owned = self._conn()
        try:
            rows = conn.execute("SELECT data::text AS data FROM publications ORDER BY created_at").fetchall()
            return [publication_from_dict(json.loads(r["data"])) for r in rows]
        finally:
            if owned:
                conn.close()


class PgIdempotencyRepository(_PgRepoMixin, IdempotencyRepository):
    def __init__(self, db: PgDatabase) -> None:
        self.db = db

    def has_processed(self, command_id: str) -> bool:
        conn, owned = self._conn()
        try:
            row = conn.execute("SELECT 1 FROM idempotency WHERE command_id = %s", (command_id,)).fetchone()
            return row is not None
        finally:
            if owned:
                conn.close()

    def mark_processed(self, command_id: str) -> None:
        conn, owned = self._conn()
        try:
            conn.execute(
                "INSERT INTO idempotency (command_id, processed_at) VALUES (%s, %s)"
                " ON CONFLICT (command_id) DO NOTHING",
                (command_id, __import__("datetime").datetime.utcnow().isoformat()),
            )
        except Exception as exc:  # noqa: BLE001
            raise translate_pg_error(exc) from exc
        finally:
            if owned:
                conn.close()


class PgMatchStatsRepository(_PgRepoMixin, MatchStatsRepository):
    """FASE 21.B3 — indexed projection of BoxScore stats (PostgreSQL).

    Upsert via ``ON CONFLICT ... DO UPDATE`` keyed by
    ``(match_external_id, player_external_id)`` / team key: replaying the same
    stats for a match overwrites rows, never duplicates them.
    """

    def __init__(self, db: PgDatabase) -> None:
        self.db = db

    def save_player_stats(
        self, match_external_id: str, season_code: SeasonCode, player_stats: Iterable[PlayerStats]
    ) -> None:
        conn, owned = self._conn()
        try:
            for ps in player_stats:
                conn.execute(
                    "INSERT INTO match_player_stats"
                    " (match_external_id, player_external_id, team_external_id, season_code,"
                    "  points, rebounds, assists, steals, blocks, turnovers, minutes, played_at, data)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)"
                    " ON CONFLICT (match_external_id, player_external_id) DO UPDATE SET"
                    "  team_external_id = EXCLUDED.team_external_id,"
                    "  season_code = EXCLUDED.season_code,"
                    "  points = EXCLUDED.points, rebounds = EXCLUDED.rebounds,"
                    "  assists = EXCLUDED.assists, steals = EXCLUDED.steals,"
                    "  blocks = EXCLUDED.blocks, turnovers = EXCLUDED.turnovers,"
                    "  minutes = EXCLUDED.minutes, played_at = EXCLUDED.played_at,"
                    "  data = EXCLUDED.data",
                    (
                        match_external_id,
                        ps.player_external_id,
                        ps.team_external_id,
                        str(season_code),
                        ps.points,
                        ps.rebounds,
                        ps.assists,
                        ps.steals,
                        ps.blocks,
                        ps.turnovers,
                        ps.minutes,
                        ps.played_at,
                        json.dumps(ps.to_dict()),
                    ),
                )
        except Exception as exc:  # noqa: BLE001
            raise translate_pg_error(exc) from exc
        finally:
            if owned:
                conn.close()

    def save_team_stats(
        self, match_external_id: str, season_code: SeasonCode, team_stats: Iterable[TeamStats]
    ) -> None:
        conn, owned = self._conn()
        try:
            for ts in team_stats:
                conn.execute(
                    "INSERT INTO match_team_stats"
                    " (match_external_id, team_external_id, season_code, points_for, points_against,"
                    "  field_goals_made, field_goals_attempted, three_points_made, three_points_attempted,"
                    "  free_throws_made, free_throws_attempted, turnovers, rebounds, data)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)"
                    " ON CONFLICT (match_external_id, team_external_id) DO UPDATE SET"
                    "  season_code = EXCLUDED.season_code,"
                    "  points_for = EXCLUDED.points_for, points_against = EXCLUDED.points_against,"
                    "  field_goals_made = EXCLUDED.field_goals_made,"
                    "  field_goals_attempted = EXCLUDED.field_goals_attempted,"
                    "  three_points_made = EXCLUDED.three_points_made,"
                    "  three_points_attempted = EXCLUDED.three_points_attempted,"
                    "  free_throws_made = EXCLUDED.free_throws_made,"
                    "  free_throws_attempted = EXCLUDED.free_throws_attempted,"
                    "  turnovers = EXCLUDED.turnovers, rebounds = EXCLUDED.rebounds,"
                    "  data = EXCLUDED.data",
                    (
                        match_external_id,
                        ts.team_external_id,
                        str(season_code),
                        ts.points_for,
                        ts.points_against,
                        ts.field_goals_made,
                        ts.field_goals_attempted,
                        ts.three_points_made,
                        ts.three_points_attempted,
                        ts.free_throws_made,
                        ts.free_throws_attempted,
                        ts.turnovers,
                        ts.rebounds,
                        json.dumps(ts.to_dict()),
                    ),
                )
        except Exception as exc:  # noqa: BLE001
            raise translate_pg_error(exc) from exc
        finally:
            if owned:
                conn.close()

    def list_player_stats(self, match_external_id: str) -> Iterable[PlayerStats]:
        conn, owned = self._conn()
        try:
            rows = conn.execute(
                "SELECT data::text AS data FROM match_player_stats WHERE match_external_id = %s",
                (match_external_id,),
            ).fetchall()
            return [_player_stats_from_blob(r["data"]) for r in rows]
        finally:
            if owned:
                conn.close()

    def list_team_stats(self, match_external_id: str) -> Iterable[TeamStats]:
        conn, owned = self._conn()
        try:
            rows = conn.execute(
                "SELECT data::text AS data FROM match_team_stats WHERE match_external_id = %s",
                (match_external_id,),
            ).fetchall()
            return [TeamStats(**json.loads(r["data"])) for r in rows]
        finally:
            if owned:
                conn.close()

    def list_player_stats_by_season(
        self, player_external_id: str, season_code: SeasonCode
    ) -> Iterable[PlayerStats]:
        conn, owned = self._conn()
        try:
            rows = conn.execute(
                "SELECT data::text AS data FROM match_player_stats"
                " WHERE player_external_id = %s AND season_code = %s",
                (player_external_id, str(season_code)),
            ).fetchall()
            return [_player_stats_from_blob(r["data"]) for r in rows]
        finally:
            if owned:
                conn.close()

    def list_season_player_aggregates(
        self, season_code: SeasonCode
    ) -> Iterable[SeasonPlayerStats]:
        conn, owned = self._conn()
        try:
            rows = conn.execute(
                "SELECT"
                "  player_external_id,"
                "  season_code,"
                "  COUNT(match_external_id) AS games_played,"
                "  SUM(points) AS points,"
                "  SUM(rebounds) AS rebounds,"
                "  SUM(assists) AS assists,"
                "  SUM(steals) AS steals,"
                "  SUM(blocks) AS blocks,"
                "  SUM(turnovers) AS turnovers,"
                "  SUM(minutes) AS minutes"
                " FROM match_player_stats"
                " WHERE season_code = %s"
                " GROUP BY player_external_id, season_code"
                " ORDER BY player_external_id",
                (str(season_code),),
            ).fetchall()
            return [
                SeasonPlayerStats(
                    player_external_id=r["player_external_id"],
                    season_code=r["season_code"],
                    games_played=int(r["games_played"]),
                    points=int(r["points"]),
                    rebounds=int(r["rebounds"]),
                    assists=int(r["assists"]),
                    steals=int(r["steals"]),
                    blocks=int(r["blocks"]),
                    turnovers=int(r["turnovers"]),
                    minutes=float(r["minutes"]),
                )
                for r in rows
            ]
        finally:
            if owned:
                conn.close()

    def list_season_team_aggregates(
        self, season_code: SeasonCode
    ) -> Iterable[SeasonTeamStats]:
        """Aggregate match_team_stats for the given season.

        wins/losses are computed per-match as:
            win  → points_for > points_against
            loss → points_for < points_against
        Basketball overtime always produces a winner so ties cannot occur.
        """
        conn, owned = self._conn()
        try:
            rows = conn.execute(
                "SELECT"
                "  team_external_id,"
                "  season_code,"
                "  COUNT(match_external_id)                                     AS games_played,"
                "  SUM(CASE WHEN points_for > points_against THEN 1 ELSE 0 END) AS wins,"
                "  SUM(CASE WHEN points_for < points_against THEN 1 ELSE 0 END) AS losses,"
                "  SUM(points_for)             AS points_for,"
                "  SUM(points_against)         AS points_against,"
                "  SUM(field_goals_made)       AS field_goals_made,"
                "  SUM(field_goals_attempted)  AS field_goals_attempted,"
                "  SUM(three_points_made)      AS three_points_made,"
                "  SUM(three_points_attempted) AS three_points_attempted,"
                "  SUM(free_throws_made)       AS free_throws_made,"
                "  SUM(free_throws_attempted)  AS free_throws_attempted,"
                "  SUM(turnovers)              AS turnovers,"
                "  SUM(rebounds)               AS rebounds"
                " FROM match_team_stats"
                " WHERE season_code = %s"
                " GROUP BY team_external_id, season_code"
                " ORDER BY team_external_id",
                (str(season_code),),
            ).fetchall()
            return [
                SeasonTeamStats(
                    team_external_id=r["team_external_id"],
                    season_code=r["season_code"],
                    games_played=int(r["games_played"]),
                    wins=int(r["wins"]),
                    losses=int(r["losses"]),
                    points_for=int(r["points_for"]),
                    points_against=int(r["points_against"]),
                    field_goals_made=int(r["field_goals_made"]),
                    field_goals_attempted=int(r["field_goals_attempted"]),
                    three_points_made=int(r["three_points_made"]),
                    three_points_attempted=int(r["three_points_attempted"]),
                    free_throws_made=int(r["free_throws_made"]),
                    free_throws_attempted=int(r["free_throws_attempted"]),
                    turnovers=int(r["turnovers"]),
                    rebounds=int(r["rebounds"]),
                )
                for r in rows
            ]
        finally:
            if owned:
                conn.close()

    def list_season_player_leaderboard(
        self,
        season_code: SeasonCode,
        metric: str,
        limit: Optional[int] = None,
    ) -> Iterable[SeasonPlayerLeaderboardEntry]:
        """Ranked player leaderboard resolved in SQL (ROW_NUMBER)."""
        order_by = _PLAYER_LEADERBOARD_ORDER.get(metric)
        if order_by is None:
            raise ValueError(
                f"Unknown player metric '{metric}'. "
                f"Valid values: {PlayerLeaderboardMetric.ALL}"
            )
        conn, owned = self._conn()
        try:
            sql = (
                "WITH agg AS ("
                " SELECT player_external_id, season_code,"
                "  COUNT(match_external_id) AS games_played,"
                "  SUM(points) AS points, SUM(rebounds) AS rebounds,"
                "  SUM(assists) AS assists, SUM(steals) AS steals,"
                "  SUM(blocks) AS blocks, SUM(turnovers) AS turnovers,"
                "  SUM(minutes) AS minutes"
                " FROM match_player_stats WHERE season_code = %s"
                " GROUP BY player_external_id, season_code)"
                f" SELECT ROW_NUMBER() OVER (ORDER BY {order_by}) AS rank,"
                "  player_external_id, season_code, games_played, points, rebounds,"
                "  assists, steals, blocks, turnovers, minutes"
                f" FROM agg ORDER BY {order_by}"
            )
            params: tuple = (str(season_code),)
            if limit is not None:
                sql += " LIMIT %s"
                params += (limit,)
            rows = conn.execute(sql, params).fetchall()
            return [
                SeasonPlayerLeaderboardEntry(
                    rank=int(r["rank"]),
                    player_external_id=r["player_external_id"],
                    season_code=r["season_code"],
                    games_played=int(r["games_played"]),
                    points=int(r["points"]),
                    rebounds=int(r["rebounds"]),
                    assists=int(r["assists"]),
                    steals=int(r["steals"]),
                    blocks=int(r["blocks"]),
                    turnovers=int(r["turnovers"]),
                    minutes=float(r["minutes"]),
                )
                for r in rows
            ]
        except Exception as exc:  # noqa: BLE001 - classify at the boundary
            raise translate_pg_error(exc) from exc
        finally:
            if owned:
                conn.close()

    def list_season_team_leaderboard(
        self,
        season_code: SeasonCode,
        metric: str,
        limit: Optional[int] = None,
    ) -> Iterable[SeasonTeamLeaderboardEntry]:
        """Ranked team leaderboard resolved in SQL (ROW_NUMBER)."""
        order_by = _TEAM_LEADERBOARD_ORDER.get(metric)
        if order_by is None:
            raise ValueError(
                f"Unknown team metric '{metric}'. "
                f"Valid values: {TeamLeaderboardMetric.ALL}"
            )
        conn, owned = self._conn()
        try:
            sql = (
                "WITH agg AS ("
                " SELECT team_external_id, season_code,"
                "  COUNT(match_external_id) AS games_played,"
                "  SUM(CASE WHEN points_for > points_against THEN 1 ELSE 0 END) AS wins,"
                "  SUM(CASE WHEN points_for < points_against THEN 1 ELSE 0 END) AS losses,"
                "  SUM(points_for) AS points_for, SUM(points_against) AS points_against,"
                "  SUM(field_goals_made) AS field_goals_made,"
                "  SUM(field_goals_attempted) AS field_goals_attempted,"
                "  SUM(three_points_made) AS three_points_made,"
                "  SUM(three_points_attempted) AS three_points_attempted,"
                "  SUM(free_throws_made) AS free_throws_made,"
                "  SUM(free_throws_attempted) AS free_throws_attempted,"
                "  SUM(turnovers) AS turnovers, SUM(rebounds) AS rebounds"
                " FROM match_team_stats WHERE season_code = %s"
                " GROUP BY team_external_id, season_code)"
                f" SELECT ROW_NUMBER() OVER (ORDER BY {order_by}) AS rank,"
                "  team_external_id, season_code, games_played, wins, losses,"
                "  points_for, points_against,"
                "  (points_for - points_against) AS point_difference,"
                "  CASE WHEN games_played > 0 THEN CAST(wins AS REAL) / games_played"
                "   ELSE 0.0 END AS win_percentage"
                f" FROM agg ORDER BY {order_by}"
            )
            params: tuple = (str(season_code),)
            if limit is not None:
                sql += " LIMIT %s"
                params += (limit,)
            rows = conn.execute(sql, params).fetchall()
            return [
                SeasonTeamLeaderboardEntry(
                    rank=int(r["rank"]),
                    team_external_id=r["team_external_id"],
                    season_code=r["season_code"],
                    games_played=int(r["games_played"]),
                    wins=int(r["wins"]),
                    losses=int(r["losses"]),
                    points_for=int(r["points_for"]),
                    points_against=int(r["points_against"]),
                    point_difference=int(r["point_difference"]),
                    win_percentage=float(r["win_percentage"]),
                )
                for r in rows
            ]
        except Exception as exc:  # noqa: BLE001 - classify at the boundary
            raise translate_pg_error(exc) from exc
        finally:
            if owned:
                conn.close()


def _player_stats_from_blob(data: str) -> PlayerStats:
    """Reconstruct a PlayerStats from its JSON blob, parsing played_at (ISO
    string in storage) back to a datetime so re-serialization round-trips."""
    from datetime import datetime

    raw = json.loads(data)
    played_at = raw.get("played_at")
    if played_at:
        raw["played_at"] = datetime.fromisoformat(played_at)
    return PlayerStats(**raw)