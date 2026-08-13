"""SQLite repositories implementing the application repository interfaces.

Every repository reconstructs aggregates exclusively through the serialization
module (application.persistence.serialization): the JSON `data` blob of a row is
the source of truth, and the normalized key columns only serve lookups. No SQL
lives in Domain or Application handlers.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Iterable, List, Optional

from ...application.persistence.serialization import (
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
from ...application.repositories.interfaces import (
    CompetitionRepository,
    CorrectionRepository,
    IdempotencyRepository,
    LeaderboardRepository,
    MatchRepository,
    PlayerRepository,
    PublicationRepository,
    RatingRepository,
    StandingRepository,
    TeamRepository,
)
from ...domain.competition.model import Competition
from ...domain.correction.model import CorrectionProposal
from ...domain.leaderboard.model import Leaderboard
from ...domain.match.model import Match
from ...domain.player.model import Player
from ...domain.publication.model import Publication
from ...domain.ratings.model import PlayerRating
from ...domain.standings.model import StandingSnapshot
from ...domain.team.model import Team
from ...domain.value_objects import (
    CompetitionId,
    ExternalId,
    LeaderboardId,
    SeasonCode,
)
from .connection import SqliteDatabase, active_connection
from .errors import CorruptedRecordError, InfrastructureError, StaleVersionError


class _SqliteRepoMixin:
    db: SqliteDatabase

    def _conn(self) -> tuple:
        active = active_connection()
        if active is not None:
            return active, False
        return self.db.connect(), True

    def _fetch_data(self, table: str, where: str, params: tuple) -> Optional[str]:
        conn, owned = self._conn()
        try:
            row = conn.execute(f"SELECT data FROM {table} WHERE {where}", params).fetchone()
            return row["data"] if row is not None else None
        finally:
            if owned:
                conn.close()

    def _deserialize(self, table: str, identity: str, data: str, converter) -> object:
        """Parse+reconstruct a stored blob, classifying corruption as an
        infrastructure error instead of leaking a raw JSON exception."""
        try:
            return converter(json.loads(data))
        except (json.JSONDecodeError, TypeError, ValueError, KeyError) as exc:
            raise CorruptedRecordError(f"{table} {identity} is corrupt: {exc}") from exc


class SqliteMatchRepository(_SqliteRepoMixin, MatchRepository):
    def __init__(self, db: SqliteDatabase) -> None:
        self.db = db

    def save(self, match: Match) -> None:
        """Persist a match with an optimistic-concurrency guard.

        * No row with ``external_id`` yet  -> INSERT (new aggregate).
        * Row exists                       -> version-checked UPDATE: the stored
          ``version`` must be exactly ``match.version - 1`` (every domain mutation
          bumps the version, so the caller mutated a snapshot one version older
          than the store). A mismatch raises ``StaleVersionError`` and the write
          is NOT applied, so concurrent writers never silently overwrite.
        """
        conn, owned = self._conn()
        try:
            existing = conn.execute(
                "SELECT version FROM matches WHERE external_id = ?",
                (str(match.external_id),),
            ).fetchone()
            if existing is None:
                conn.execute(
                    "INSERT INTO matches"
                    " (match_id, external_id, competition_id, season_code, status, version, data)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
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
                "UPDATE matches SET match_id = ?, competition_id = ?, season_code = ?,"
                " status = ?, version = ?, data = ?"
                " WHERE external_id = ? AND version = ?",
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
        finally:
            if owned:
                conn.close()

    def get_by_external_id(self, external_id: ExternalId) -> Optional[Match]:
        data = self._fetch_data("matches", "external_id = ?", (str(external_id),))
        if data is None:
            return None
        return self._deserialize("matches", str(external_id), data, match_from_dict)

    def list_by_season(self, competition_id: CompetitionId, season_code: SeasonCode) -> Iterable[Match]:
        conn, owned = self._conn()
        try:
            rows = conn.execute(
                "SELECT data FROM matches WHERE competition_id = ? AND season_code = ?",
                (str(competition_id), str(season_code)),
            ).fetchall()
            return [match_from_dict(json.loads(r["data"])) for r in rows]
        finally:
            if owned:
                conn.close()


class SqlitePlayerRepository(_SqliteRepoMixin, PlayerRepository):
    def __init__(self, db: SqliteDatabase) -> None:
        self.db = db

    def save(self, player: Player) -> None:
        conn, owned = self._conn()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO players (player_id, external_id, name, data) VALUES (?, ?, ?, ?)",
                (str(player.player_id), str(player.external_id), player.name, json.dumps(player_to_dict(player))),
            )
        finally:
            if owned:
                conn.close()

    def get_by_external_id(self, external_id: ExternalId) -> Optional[Player]:
        data = self._fetch_data("players", "external_id = ?", (str(external_id),))
        if data is None:
            return None
        return self._deserialize("players", str(external_id), data, player_from_dict)


class SqliteTeamRepository(_SqliteRepoMixin, TeamRepository):
    def __init__(self, db: SqliteDatabase) -> None:
        self.db = db

    def save(self, team: Team) -> None:
        conn, owned = self._conn()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO teams (team_id, external_id, name, data) VALUES (?, ?, ?, ?)",
                (str(team.team_id), str(team.external_id), team.name, json.dumps(team_to_dict(team))),
            )
        finally:
            if owned:
                conn.close()

    def get_by_external_id(self, external_id: ExternalId) -> Optional[Team]:
        data = self._fetch_data("teams", "external_id = ?", (str(external_id),))
        if data is None:
            return None
        return self._deserialize("teams", str(external_id), data, team_from_dict)


class SqliteCompetitionRepository(_SqliteRepoMixin, CompetitionRepository):
    def __init__(self, db: SqliteDatabase) -> None:
        self.db = db

    def save(self, competition: Competition) -> None:
        conn, owned = self._conn()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO competitions (competition_id, external_id, name, data) VALUES (?, ?, ?, ?)",
                (
                    str(competition.competition_id),
                    str(competition.external_id),
                    competition.name,
                    json.dumps(competition_to_dict(competition)),
                ),
            )
        finally:
            if owned:
                conn.close()

    def get_by_external_id(self, external_id: ExternalId) -> Optional[Competition]:
        data = self._fetch_data("competitions", "external_id = ?", (str(external_id),))
        if data is None:
            return None
        return self._deserialize("competitions", str(external_id), data, competition_from_dict)


class SqliteCorrectionRepository(_SqliteRepoMixin, CorrectionRepository):
    def __init__(self, db: SqliteDatabase) -> None:
        self.db = db

    def save(self, proposal: CorrectionProposal) -> None:
        conn, owned = self._conn()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO correction_proposals"
                " (proposal_id, match_external_id, status, data) VALUES (?, ?, ?, ?)",
                (
                    str(proposal.proposal_id),
                    str(proposal.match_external_id),
                    proposal.status,
                    json.dumps(correction_to_dict(proposal)),
                ),
            )
        finally:
            if owned:
                conn.close()

    def get_by_id(self, proposal_id: str) -> Optional[CorrectionProposal]:
        data = self._fetch_data("correction_proposals", "proposal_id = ?", (proposal_id,))
        if data is None:
            return None
        return self._deserialize("correction_proposals", proposal_id, data, correction_from_dict)


class SqliteStandingRepository(_SqliteRepoMixin, StandingRepository):
    def __init__(self, db: SqliteDatabase) -> None:
        self.db = db

    def save(self, standing_snapshot: StandingSnapshot) -> None:
        conn, owned = self._conn()
        try:
            conn.execute(
                "INSERT INTO standing_snapshots"
                " (snapshot_id, competition_id, season_code, generated_at, data) VALUES (?, ?, ?, ?, ?)",
                (
                    str(standing_snapshot.snapshot_id),
                    str(standing_snapshot.competition_id),
                    str(standing_snapshot.season_code),
                    standing_snapshot.generated_at.isoformat(),
                    json.dumps(standing_to_dict(standing_snapshot)),
                ),
            )
        finally:
            if owned:
                conn.close()

    def list_all(self) -> List[StandingSnapshot]:
        conn, owned = self._conn()
        try:
            rows = conn.execute("SELECT data FROM standing_snapshots ORDER BY generated_at").fetchall()
            return [standing_from_dict(json.loads(r["data"])) for r in rows]
        finally:
            if owned:
                conn.close()


class SqliteLeaderboardRepository(_SqliteRepoMixin, LeaderboardRepository):
    def __init__(self, db: SqliteDatabase) -> None:
        self.db = db

    def save(self, leaderboard: Leaderboard) -> None:
        conn, owned = self._conn()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO leaderboards"
                " (leaderboard_id, season_code, category, generated_at, data) VALUES (?, ?, ?, ?, ?)",
                (
                    str(leaderboard.leaderboard_id),
                    str(leaderboard.season_code),
                    leaderboard.category,
                    leaderboard.generated_at.isoformat(),
                    json.dumps(leaderboard_to_dict(leaderboard)),
                ),
            )
        finally:
            if owned:
                conn.close()

    def get_by_id(self, leaderboard_id: LeaderboardId) -> Optional[Leaderboard]:
        data = self._fetch_data("leaderboards", "leaderboard_id = ?", (str(leaderboard_id),))
        if data is None:
            return None
        return self._deserialize("leaderboards", str(leaderboard_id), data, leaderboard_from_dict)

    def list_all(self) -> List[Leaderboard]:
        conn, owned = self._conn()
        try:
            rows = conn.execute("SELECT data FROM leaderboards ORDER BY generated_at").fetchall()
            return [leaderboard_from_dict(json.loads(r["data"])) for r in rows]
        finally:
            if owned:
                conn.close()


class SqliteRatingRepository(_SqliteRepoMixin, RatingRepository):
    def __init__(self, db: SqliteDatabase) -> None:
        self.db = db

    def save(self, player_rating: PlayerRating) -> None:
        conn, owned = self._conn()
        try:
            conn.execute(
                "INSERT INTO ratings"
                " (player_external_id, season_code, rating_version, calculated_at, data) VALUES (?, ?, ?, ?, ?)",
                (
                    str(player_rating.player_external_id),
                    str(player_rating.season_code),
                    str(player_rating.rating_version),
                    player_rating.calculated_at.isoformat(),
                    json.dumps(rating_to_dict(player_rating)),
                ),
            )
        finally:
            if owned:
                conn.close()

    def list_all(self) -> List[PlayerRating]:
        conn, owned = self._conn()
        try:
            rows = conn.execute("SELECT data FROM ratings ORDER BY rating_id").fetchall()
            return [rating_from_dict(json.loads(r["data"])) for r in rows]
        finally:
            if owned:
                conn.close()


class SqlitePublicationRepository(_SqliteRepoMixin, PublicationRepository):
    def __init__(self, db: SqliteDatabase) -> None:
        self.db = db

    def save(self, publication: Publication) -> None:
        conn, owned = self._conn()
        try:
            # INSERT OR REPLACE: publication_id is the command_id, so replaying the same
            # command overwrites the same publication (documented deviation from the
            # in-memory append-only list, which created duplicates).
            conn.execute(
                "INSERT OR REPLACE INTO publications"
                " (publication_id, template_id, status, created_at, data) VALUES (?, ?, ?, ?, ?)",
                (
                    str(publication.publication_id),
                    publication.template_id,
                    publication.status,
                    publication.created_at.isoformat(),
                    json.dumps(publication_to_dict(publication)),
                ),
            )
        finally:
            if owned:
                conn.close()

    def list_all(self) -> List[Publication]:
        conn, owned = self._conn()
        try:
            rows = conn.execute("SELECT data FROM publications ORDER BY created_at").fetchall()
            return [publication_from_dict(json.loads(r["data"])) for r in rows]
        finally:
            if owned:
                conn.close()


class SqliteIdempotencyRepository(_SqliteRepoMixin, IdempotencyRepository):
    def __init__(self, db: SqliteDatabase) -> None:
        self.db = db

    def has_processed(self, command_id: str) -> bool:
        conn, owned = self._conn()
        try:
            row = conn.execute("SELECT 1 FROM idempotency WHERE command_id = ?", (command_id,)).fetchone()
            return row is not None
        finally:
            if owned:
                conn.close()

    def mark_processed(self, command_id: str) -> None:
        conn, owned = self._conn()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO idempotency (command_id, processed_at) VALUES (?, ?)",
                (command_id, datetime.utcnow().isoformat()),
            )
        finally:
            if owned:
                conn.close()