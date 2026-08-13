"""Composition roots (FASE 11 + FASE 12): wire the Application layer to a real
backend and implement the HTTP ``CommandGateway`` boundary.

``_GatewayBase`` holds everything the boundary needs that is backend-agnostic
(handler catalog, CommandRunner construction, read-side DTOs, readiness
template). ``SqliteGateway`` and ``PgGateway`` only provide the concrete
repositories. ``build_gateway()`` picks the backend from configuration, so
PostgreSQL can substitute SQLite without touching Domain, Application, the API or
the contracts.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, Optional

from ..api.gateway import CommandGateway, CommandResult, EventRef, Readiness
from ..application.commands.commands import COMMANDS
from ..application.use_cases.handlers import (
    ApproveCorrectionHandler,
    BackfillSeasonHandler,
    ComputePlayerRatingHandler,
    CreateOrUpdateMatchHandler,
    CreatePublicationHandler,
    FinalizeMatchHandler,
    GenerateLeaderboardHandler,
    GenerateStandingSnapshotHandler,
    ProposeCorrectionHandler,
    RegisterPlayerToSquadHandler,
)
from ..domain.value_objects import Actor, CommandMeta
from .config import settings_from_env
from .application_service import CommandRunner, as_event_list
from .logging import Logger, StdLogger
from .persistence.event_dispatcher import SyncEventDispatcher


def _to_snake(name: str) -> str:
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


class _GatewayBase(CommandGateway):
    """Backend-agnostic boundary: handler catalog + read DTOs + readiness."""

    backend_name = "unknown"

    def __init__(
        self,
        db,
        *,
        dispatcher: Optional[SyncEventDispatcher] = None,
        logger: Optional[Logger] = None,
    ) -> None:
        self.db = db
        self.logger = logger or StdLogger("feb_score.gateway")
        self.runner = CommandRunner(db, dispatcher=dispatcher, logger=self.logger)
        self.logger.log(
            "info", "gateway_ready", backend=self.backend_name,
        )

        repos = self._build_repositories()
        self._match_repo = repos["match"]
        self._player_repo = repos["player"]
        self._team_repo = repos["team"]
        self._competition_repo = repos["competition"]
        self._correction_repo = repos["correction"]
        self._leaderboard_repo = repos["leaderboard"]

        self._handlers: Dict[str, Any] = {
            "create_or_update_match": lambda: CreateOrUpdateMatchHandler(repos["match"], repos["idempotency"]),
            "finalize_match": lambda: FinalizeMatchHandler(repos["match"], repos["idempotency"]),
            "propose_correction": lambda: ProposeCorrectionHandler(repos["correction"], repos["idempotency"]),
            "approve_correction": lambda: ApproveCorrectionHandler(
                repos["correction"], repos["match"], repos["idempotency"]
            ),
            "register_player_to_squad": lambda: RegisterPlayerToSquadHandler(repos["player"], repos["team"]),
            "generate_standing_snapshot": lambda: GenerateStandingSnapshotHandler(
                repos["standing"], repos["match"], repos["idempotency"]
            ),
            "generate_leaderboard": lambda: GenerateLeaderboardHandler(
                repos["match"], repos["leaderboard"], repos["idempotency"]
            ),
            "compute_player_rating": lambda: ComputePlayerRatingHandler(
                repos["match"], repos["rating"], repos["idempotency"]
            ),
            "create_publication": lambda: CreatePublicationHandler(repos["publication"]),
            "backfill_season": lambda: BackfillSeasonHandler(repos["competition"]),
        }
        assert set(self._handlers) == set(COMMANDS), "handler catalog must match command catalog"

    def _build_repositories(self) -> Dict[str, Any]:
        raise NotImplementedError

    # ------------------------------------------------------------- commands
    def run(
        self,
        command_type: str,
        *,
        command_id: str,
        actor: Dict[str, Any],
        payload: Dict[str, Any],
    ) -> CommandResult:
        if command_type not in COMMANDS or command_type not in self._handlers:
            raise KeyError(f"unknown command: {command_type}")

        command = COMMANDS[command_type](
            command_id=command_id,
            meta=CommandMeta(version="1.0", issued_at=datetime.utcnow()),
            actor=Actor(**actor),
            payload=payload,
        )
        result = self.runner.run(self._handlers[command_type](), command)
        events = [
            EventRef(event_id=str(e.event_id), event_type=_to_snake(type(e).__name__))
            for e in as_event_list(result)
        ]
        return CommandResult(command_id=command_id, events=events)

    # ---------------------------------------------------------- read side
    def get_match(self, external_id: str) -> Optional[Dict[str, Any]]:
        match = self._match_repo.get_by_external_id(external_id)
        if match is None:
            return None
        dto: Dict[str, Any] = {
            "external_id": str(match.external_id),
            "match_id": str(match.match_id),
            "competition_id": str(match.competition_id),
            "season_code": str(match.season_code),
            "round_number": match.round_number,
            "status": match.status.value,
            "scheduled_at": match.scheduled_at.isoformat(),
            "home_team_id": str(match.home_team_id),
            "away_team_id": str(match.away_team_id),
            "version": match.version,
            "correction_history_count": len(match.correction_history),
        }
        if match.score_summary is not None:
            dto["score_summary"] = {
                "home_score": match.score_summary.home_score,
                "away_score": match.score_summary.away_score,
            }
        return dto

    def get_player(self, external_id: str) -> Optional[Dict[str, Any]]:
        player = self._player_repo.get_by_external_id(external_id)
        if player is None:
            return None
        return {
            "external_id": str(player.external_id),
            "name": player.name,
            "registrations_count": len(player.registrations),
        }

    def get_team(self, external_id: str) -> Optional[Dict[str, Any]]:
        team = self._team_repo.get_by_external_id(external_id)
        if team is None:
            return None
        return {
            "external_id": str(team.external_id),
            "name": team.name,
            "registrations_count": len(team.registrations),
        }

    def get_competition(self, external_id: str) -> Optional[Dict[str, Any]]:
        competition = self._competition_repo.get_by_external_id(external_id)
        if competition is None:
            return None
        return {
            "external_id": str(competition.external_id),
            "name": competition.name,
            "seasons": [str(code) for code in competition.seasons],
        }

    def get_leaderboard(self, leaderboard_id: str) -> Optional[Dict[str, Any]]:
        leaderboard = self._leaderboard_repo.get_by_id(leaderboard_id)
        if leaderboard is None:
            return None
        return {
            "leaderboard_id": str(leaderboard.leaderboard_id),
            "season_code": str(leaderboard.season_code),
            "category": leaderboard.category,
            "generated_at": leaderboard.generated_at.isoformat(),
            "entries": [
                {"player_external_id": e.player_external_id, "value": e.value}
                for e in leaderboard.entries
            ],
        }

    def get_correction_proposal(self, proposal_id: str) -> Optional[Dict[str, Any]]:
        proposal = self._correction_repo.get_by_id(proposal_id)
        if proposal is None:
            return None
        return {
            "proposal_id": str(proposal.proposal_id),
            "match_external_id": str(proposal.match_external_id),
            "status": proposal.status,
            "proposed_by": proposal.proposed_by.id,
            "reason": proposal.reason,
            "changes": proposal.changes,
        }

    # ------------------------------------------------------------ readiness
    def readiness(self) -> Readiness:
        """Non-destructive dependency check.

        Distinguishes (FASE 13): process alive (/health) vs dependencies healthy
        (/ready). A gateway is READY only when the database is reachable AND the
        schema is exactly at the expected migration version — pending migrations
        or a future/unknown schema both fail readiness.
        """
        checks: Dict[str, str] = {}
        try:
            checks.update(self._db_checks())
            checks["database"] = "ok"
            checks["migrations"] = self._migration_status()
            ready = checks["migrations"] == "up_to_date"
            return Readiness(ready=ready, checks=checks)
        except Exception as exc:  # noqa: BLE001 - readiness must never raise
            checks.setdefault("database", f"error: {type(exc).__name__}")
            checks.setdefault("migrations", "unknown")
            return Readiness(ready=False, checks=checks)

    def _migration_status(self) -> str:
        current = int(self._db_checks()["schema_version"])
        expected = self._expected_schema_version()
        if current < expected:
            return f"pending (schema {current} < expected {expected})"
        if current > expected:
            return f"future/unknown (schema {current} > expected {expected})"
        return "up_to_date"

    def _db_checks(self) -> Dict[str, str]:
        raise NotImplementedError

    def _expected_schema_version(self) -> int:
        raise NotImplementedError


class SqliteGateway(_GatewayBase):
    """Boundary over the SQLite infrastructure."""

    backend_name = "sqlite"

    def _build_repositories(self) -> Dict[str, Any]:
        from .persistence.connection import SqliteDatabase
        from .persistence.repositories import (
            SqliteCompetitionRepository,
            SqliteCorrectionRepository,
            SqliteIdempotencyRepository,
            SqliteLeaderboardRepository,
            SqliteMatchRepository,
            SqlitePlayerRepository,
            SqlitePublicationRepository,
            SqliteRatingRepository,
            SqliteStandingRepository,
            SqliteTeamRepository,
        )

        return {
            "idempotency": SqliteIdempotencyRepository(self.db),
            "match": SqliteMatchRepository(self.db),
            "player": SqlitePlayerRepository(self.db),
            "team": SqliteTeamRepository(self.db),
            "competition": SqliteCompetitionRepository(self.db),
            "correction": SqliteCorrectionRepository(self.db),
            "standing": SqliteStandingRepository(self.db),
            "leaderboard": SqliteLeaderboardRepository(self.db),
            "rating": SqliteRatingRepository(self.db),
            "publication": SqlitePublicationRepository(self.db),
        }

    def _db_checks(self) -> Dict[str, str]:
        from .persistence.connection import SqliteDatabase

        assert isinstance(self.db, SqliteDatabase)
        conn = self.db.connect()
        try:
            conn.execute("SELECT 1").fetchone()
            return {"schema_version": str(self.db.user_version)}
        finally:
            conn.close()

    def _expected_schema_version(self) -> int:
        from .persistence.connection import MIGRATIONS as SQLITE_MIGRATIONS

        return len(SQLITE_MIGRATIONS)


class PgGateway(_GatewayBase):
    """Boundary over the PostgreSQL infrastructure (FASE 12)."""

    backend_name = "postgresql"

    def _build_repositories(self) -> Dict[str, Any]:
        from .persistence.postgres.repositories import (
            PgCompetitionRepository,
            PgCorrectionRepository,
            PgIdempotencyRepository,
            PgLeaderboardRepository,
            PgMatchRepository,
            PgPlayerRepository,
            PgPublicationRepository,
            PgRatingRepository,
            PgStandingRepository,
            PgTeamRepository,
        )

        return {
            "idempotency": PgIdempotencyRepository(self.db),
            "match": PgMatchRepository(self.db),
            "player": PgPlayerRepository(self.db),
            "team": PgTeamRepository(self.db),
            "competition": PgCompetitionRepository(self.db),
            "correction": PgCorrectionRepository(self.db),
            "standing": PgStandingRepository(self.db),
            "leaderboard": PgLeaderboardRepository(self.db),
            "rating": PgRatingRepository(self.db),
            "publication": PgPublicationRepository(self.db),
        }

    def _db_checks(self) -> Dict[str, str]:
        from .persistence.postgres.connection import PgDatabase

        assert isinstance(self.db, PgDatabase)
        conn = self.db.connect()
        try:
            conn.execute("SELECT 1").fetchone()
            return {"schema_version": str(self.db.schema_version())}
        finally:
            conn.close()

    def _expected_schema_version(self) -> int:
        from .persistence.postgres.connection import MIGRATIONS as PG_MIGRATIONS

        return len(PG_MIGRATIONS)


def build_gateway(
    db=None,
    *,
    dispatcher: Optional[SyncEventDispatcher] = None,
    logger: Optional[Logger] = None,
) -> CommandGateway:
    """Compose the application boundary from configuration.

    * ``FEB_SCORE_DATABASE_URL`` set  -> PostgreSQL backend (PgDatabase + PgGateway).
    * otherwise                        -> SQLite backend (default ``FEB_SCORE_DB``).
    A ``db`` passed explicitly always wins (tests inject their own backend).
    """
    settings = settings_from_env()
    if db is not None:
        return _gateway_for(db, dispatcher=dispatcher, logger=logger)
    if settings.database_url:
        from .persistence.postgres.connection import PgDatabase

        pg_db = PgDatabase(settings.database_url)
        pg_db.migrate()
        return PgGateway(pg_db, dispatcher=dispatcher, logger=logger)
    from .persistence.connection import SqliteDatabase

    sqlite_db = SqliteDatabase(settings.db_path)
    sqlite_db.migrate()
    return SqliteGateway(sqlite_db, dispatcher=dispatcher, logger=logger)


def _gateway_for(db, *, dispatcher, logger) -> CommandGateway:
    from .persistence.connection import SqliteDatabase
    from .persistence.postgres.connection import PgDatabase

    if isinstance(db, PgDatabase):
        return PgGateway(db, dispatcher=dispatcher, logger=logger)
    if isinstance(db, SqliteDatabase):
        return SqliteGateway(db, dispatcher=dispatcher, logger=logger)
    raise TypeError(f"unsupported database backend: {type(db).__name__}")