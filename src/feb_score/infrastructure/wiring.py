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
from typing import Any, Dict, List, Optional

from ..api.gateway import CommandGateway, CommandResult, EventRef, Readiness
from ..application.commands.commands import COMMANDS
from ..application.use_cases.content_service import ContentService
from ..application.use_cases.exploration_service import ExplorationService
from ..application.use_cases.live_content_adapter import LiveContentAdapter
from ..application.use_cases.round_pipeline import RoundPipeline
from ..application.use_cases.handlers import (
    ApproveCorrectionHandler,
    BackfillCatalogHandler,
    BackfillSeasonHandler,
    ComputePlayerRatingHandler,
    CreateOrUpdateMatchHandler,
    CreatePublicationHandler,
    FinalizeMatchHandler,
    GenerateLeaderboardHandler,
    GenerateStandingSnapshotHandler,
    ProposeCorrectionHandler,
    RegisterPlayerToSquadHandler,
    UpsertMatchStatsHandler,
)
from ..application.use_cases.season_analytics_service import SeasonAnalyticsService
from ..domain.statistics.model import (
    SeasonPlayerLeaderboardEntry,
    SeasonPlayerMetrics,
    SeasonPlayerStats,
    SeasonTeamLeaderboardEntry,
    SeasonTeamMetrics,
    SeasonTeamStats,
)
from ..domain.value_objects import Actor, CommandMeta, CompetitionId, ExternalId, SeasonCode
from .config import settings_from_env
from .application_service import CommandRunner, as_event_list
from .logging import Logger, StdLogger
from .persistence.event_dispatcher import SyncEventDispatcher


def _to_snake(name: str) -> str:
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


# ------------------------------------------------------------- FASE 23.5 DTOs
def _player_aggregate_dto(a: SeasonPlayerStats) -> Dict[str, Any]:
    return {
        "player_external_id": a.player_external_id,
        "season_code": a.season_code,
        "games_played": a.games_played,
        "points": a.points,
        "rebounds": a.rebounds,
        "assists": a.assists,
        "steals": a.steals,
        "blocks": a.blocks,
        "turnovers": a.turnovers,
        "minutes": a.minutes,
    }


def _team_aggregate_dto(a: SeasonTeamStats) -> Dict[str, Any]:
    return {
        "team_external_id": a.team_external_id,
        "season_code": a.season_code,
        "games_played": a.games_played,
        "wins": a.wins,
        "losses": a.losses,
        "points_for": a.points_for,
        "points_against": a.points_against,
        "field_goals_made": a.field_goals_made,
        "field_goals_attempted": a.field_goals_attempted,
        "three_points_made": a.three_points_made,
        "three_points_attempted": a.three_points_attempted,
        "free_throws_made": a.free_throws_made,
        "free_throws_attempted": a.free_throws_attempted,
        "turnovers": a.turnovers,
        "rebounds": a.rebounds,
    }


def _player_leaderboard_dto(e: SeasonPlayerLeaderboardEntry) -> Dict[str, Any]:
    return {
        "rank": e.rank,
        "player_external_id": e.player_external_id,
        "season_code": e.season_code,
        "games_played": e.games_played,
        "points": e.points,
        "rebounds": e.rebounds,
        "assists": e.assists,
        "steals": e.steals,
        "blocks": e.blocks,
        "turnovers": e.turnovers,
        "minutes": e.minutes,
    }


def _team_leaderboard_dto(e: SeasonTeamLeaderboardEntry) -> Dict[str, Any]:
    return {
        "rank": e.rank,
        "team_external_id": e.team_external_id,
        "season_code": e.season_code,
        "games_played": e.games_played,
        "wins": e.wins,
        "losses": e.losses,
        "points_for": e.points_for,
        "points_against": e.points_against,
        "point_difference": e.point_difference,
        "win_percentage": e.win_percentage,
    }


def _player_metrics_dto(m: SeasonPlayerMetrics) -> Dict[str, Any]:
    return {
        "player_external_id": m.player_external_id,
        "season_code": m.season_code,
        "games_played": m.games_played,
        "points": m.points,
        "points_per_game": m.points_per_game,
        "rebounds": m.rebounds,
        "rebounds_per_game": m.rebounds_per_game,
        "assists": m.assists,
        "assists_per_game": m.assists_per_game,
        "steals": m.steals,
        "steals_per_game": m.steals_per_game,
        "blocks": m.blocks,
        "blocks_per_game": m.blocks_per_game,
        "turnovers": m.turnovers,
        "turnovers_per_game": m.turnovers_per_game,
        "minutes": m.minutes,
        "minutes_per_game": m.minutes_per_game,
    }


def _team_metrics_dto(m: SeasonTeamMetrics) -> Dict[str, Any]:
    return {
        "team_external_id": m.team_external_id,
        "season_code": m.season_code,
        "games_played": m.games_played,
        "wins": m.wins,
        "losses": m.losses,
        "points_for": m.points_for,
        "points_against": m.points_against,
        "points_per_game": m.points_per_game,
        "points_against_per_game": m.points_against_per_game,
        "point_difference_per_game": m.point_difference_per_game,
        "win_percentage": m.win_percentage,
        "field_goals_made_per_game": m.field_goals_made_per_game,
        "field_goals_attempted_per_game": m.field_goals_attempted_per_game,
        "three_points_made_per_game": m.three_points_made_per_game,
        "three_points_attempted_per_game": m.three_points_attempted_per_game,
        "free_throws_made_per_game": m.free_throws_made_per_game,
        "free_throws_attempted_per_game": m.free_throws_attempted_per_game,
        "turnovers_per_game": m.turnovers_per_game,
        "rebounds_per_game": m.rebounds_per_game,
    }


def _match_summary_dto(match) -> Dict[str, Any]:
    """Match core fields shared by the match detail and match search reads.

    ``score_summary`` is included only when the aggregate stores one (the read
    models never infer a score from the boxscore projection).
    """
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
    }
    if match.score_summary is not None:
        dto["score_summary"] = {
            "home_score": match.score_summary.home_score,
            "away_score": match.score_summary.away_score,
        }
    return dto


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
        self._stats_repo = repos["stats"]
        self._analytics = SeasonAnalyticsService(self._stats_repo)
        self._exploration = ExplorationService(
            repos["match"], repos["player"], repos["team"], repos["stats"]
        )
        self._content = ContentService(repos["match"], repos["stats"])

        # Content Engine pipeline (live data). Lazily constructed on first use
        # so gateways that never touch content don't pay the renderer setup.
        self._content_adapter = LiveContentAdapter(
            repos["match"], repos["stats"], repos["player"], repos["team"]
        )
        self._content_queue_repo = repos["content_queue"]
        self._content_pipeline: Optional[RoundPipeline] = None
        self._content_lifecycle = None  # lazily built alongside the pipeline

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
            "upsert_match_stats": lambda: UpsertMatchStatsHandler(
                repos["match"], repos["stats"], repos["idempotency"]
            ),
            "backfill_catalog": lambda: BackfillCatalogHandler(
                repos["match"], repos["stats"], repos["player"], repos["team"]
            ),
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
        detail = self._exploration.get_match_detail(ExternalId(external_id))
        if detail is None:
            return None
        match = detail.match
        dto = _match_summary_dto(match)
        dto["version"] = match.version
        dto["correction_history_count"] = len(match.correction_history)
        # FASE 24.1 — boxscore projection (authoritative MatchStatsRepository
        # read model; the aggregate's embedded stats are never used here).
        dto["team_stats"] = [ts.to_dict() for ts in detail.team_stats]
        dto["player_stats"] = [ps.to_dict() for ps in detail.player_stats]
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

    # ------------------------------------------------ FASE 23.5 season reads
    def list_season_player_aggregates(
        self, season_code: str, limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        return [
            _player_aggregate_dto(a)
            for a in self._analytics.list_season_player_aggregates(SeasonCode(season_code), limit)
        ]

    def list_season_team_aggregates(
        self, season_code: str, limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        return [
            _team_aggregate_dto(a)
            for a in self._analytics.list_season_team_aggregates(SeasonCode(season_code), limit)
        ]

    def list_season_player_leaderboard(
        self, season_code: str, metric: str, limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        return [
            _player_leaderboard_dto(e)
            for e in self._analytics.list_season_player_leaderboard(
                SeasonCode(season_code), metric, limit
            )
        ]

    def list_season_team_leaderboard(
        self, season_code: str, metric: str, limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        return [
            _team_leaderboard_dto(e)
            for e in self._analytics.list_season_team_leaderboard(
                SeasonCode(season_code), metric, limit
            )
        ]

    def list_season_player_metrics(
        self, season_code: str, limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        return [
            _player_metrics_dto(m)
            for m in self._analytics.list_season_player_metrics(SeasonCode(season_code), limit)
        ]

    def list_season_team_metrics(
        self, season_code: str, limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        return [
            _team_metrics_dto(m)
            for m in self._analytics.list_season_team_metrics(SeasonCode(season_code), limit)
        ]

    # ------------------------------------------------ FASE 24 exploration
    def get_match_detail(self, external_id: str) -> Optional[Dict[str, Any]]:
        return self.get_match(external_id)

    def get_player_profile(
        self, season_code: str, player_external_id: str
    ) -> Optional[Dict[str, Any]]:
        profile = self._exploration.get_player_profile(SeasonCode(season_code), player_external_id)
        if profile is None:
            return None
        dto: Dict[str, Any] = {
            "player_external_id": str(profile.player.external_id) if profile.player else player_external_id,
            "name": profile.player.name if profile.player else None,
            "position": profile.player.position if profile.player else None,
            "nationality": profile.player.nationality if profile.player else None,
            "birth_date": (
                profile.player.birth_date.isoformat()
                if profile.player and profile.player.birth_date
                else None
            ),
            "season_code": profile.season_code,
            "teams": [
                {
                    "team_external_id": reg.team_external_id,
                    "dorsal": reg.dorsal,
                    "role": reg.role,
                }
                for reg in profile.teams
            ],
            "totals": _player_aggregate_dto(profile.totals) if profile.totals is not None else None,
            "metrics": _player_metrics_dto(profile.metrics) if profile.metrics is not None else None,
        }
        return dto

    def get_team_profile(
        self, season_code: str, team_external_id: str
    ) -> Optional[Dict[str, Any]]:
        profile = self._exploration.get_team_profile(SeasonCode(season_code), team_external_id)
        if profile is None:
            return None
        return {
            "team_external_id": str(profile.team.external_id) if profile.team else team_external_id,
            "name": profile.team.name if profile.team else None,
            "season_code": profile.season_code,
            "totals": _team_aggregate_dto(profile.totals) if profile.totals is not None else None,
            "metrics": _team_metrics_dto(profile.metrics) if profile.metrics is not None else None,
            "evolution": [
                {
                    "round_number": r.round_number,
                    "games_played": r.games_played,
                    "wins": r.wins,
                    "losses": r.losses,
                    "points_for": r.points_for,
                    "points_against": r.points_against,
                    "point_difference": r.point_difference,
                }
                for r in profile.rounds
            ],
        }

    def search_players(self, q: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        return [
            {"player_external_id": str(p.external_id), "name": p.name}
            for p in self._exploration.search_players(q, limit)
        ]

    def search_teams(self, q: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        return [
            {"team_external_id": str(t.external_id), "name": t.name}
            for t in self._exploration.search_teams(q, limit)
        ]

    def search_matches(
        self,
        season_code: str,
        *,
        competition_id: Optional[str] = None,
        round_number: Optional[int] = None,
        team_external_id: Optional[str] = None,
        q: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        competition = CompetitionId(competition_id) if competition_id is not None else None
        return [
            _match_summary_dto(m)
            for m in self._exploration.search_matches(
                SeasonCode(season_code),
                competition_id=competition,
                round_number=round_number,
                team_external_id=team_external_id,
                external_id_query=q,
                limit=limit,
            )
        ]

    # ----------------------------------------------------- FASE 27 analytics
    def list_power_ranking(
        self, season_code: str, limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        entries = self._analytics.list_power_ranking(SeasonCode(season_code), limit)
        return [e.to_dict() for e in entries]

    def get_player_form_index(
        self, season_code: str, player_external_id: str, window: int = 5
    ) -> Optional[Dict[str, Any]]:
        fi = self._analytics.get_player_form_index(
            SeasonCode(season_code), player_external_id, window
        )
        return fi.to_dict() if fi is not None else None

    def get_team_form_index(
        self, season_code: str, team_external_id: str, window: int = 5
    ) -> Optional[Dict[str, Any]]:
        fi = self._analytics.get_team_form_index(
            SeasonCode(season_code), team_external_id, window
        )
        return fi.to_dict() if fi is not None else None

    # ---------------------------------------------------- content engine
    def generate_match_result_content(
        self, match_external_id: str
    ) -> Optional[Dict[str, Any]]:
        from ..domain.errors import ContentGenerationError, MatchNotFound

        try:
            content = self._content.generate_match_result(match_external_id)
            return content.to_dict()
        except (MatchNotFound, ContentGenerationError):
            return None

    def _pipeline(self) -> RoundPipeline:
        if self._content_pipeline is None:
            from .rendering.asset_provider import StatisticalAssetProvider
            from .rendering.design_system import DESIGN_SYSTEM_VERSION
            from .rendering.svg_renderer import ComponentSvgRenderer

            self._content_pipeline = RoundPipeline(
                renderer=ComponentSvgRenderer(),
                assets=StatisticalAssetProvider(),
                queue=self._content_queue_repo,
                design_system_version=DESIGN_SYSTEM_VERSION,
            )
        return self._content_pipeline

    def run_content_pipeline(
        self, season_code: str, round_number: int, top_n: int = 5
    ) -> Dict[str, Any]:
        inputs = self._content_adapter.build_round_inputs(season_code, round_number)
        season_context = self._content_adapter.build_season_context(
            season_code, round_number, inputs
        )
        pipeline = self._pipeline()
        result = pipeline.run(
            inputs.season_code,
            inputs.round_number,
            inputs.matches,
            inputs.player_lines,
            top_n=top_n,
            season_context=season_context,
        )
        return {
            "season_code": season_code,
            "round_number": round_number,
            "matches_considered": len(inputs.matches),
            "content_generated": len(result.items),
            "metrics": result.metrics.to_dict(),
            "items": [i.to_dict() for i in result.items],
            "pending_template": [s.to_dict() for s in result.pending_template],
        }

    def list_content_queue(
        self, status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        from ..domain.content.queue import ContentStatus

        queue = self._pipeline().queue
        if status is not None:
            try:
                items = queue.list_by_status(ContentStatus(status))
            except ValueError:
                raise ValueError(f"invalid status {status!r}")
        else:
            items = sorted(
                queue.all(), key=lambda i: (-i.story.priority, i.created_at)
            )
        return [i.to_dict() for i in items]

    def get_content_item(self, content_id: str) -> Optional[Dict[str, Any]]:
        item = self._pipeline().queue.get(content_id)
        return item.to_dict() if item is not None else None

    def render_content_item(self, content_id: str) -> Optional[str]:
        item = self._pipeline().queue.get(content_id)
        if item is None:
            return None
        return item.rendered_svg

    # ----------------------------------------------- content lifecycle actions
    def _lifecycle(self):
        if self._content_lifecycle is None:
            from ..application.use_cases.content_lifecycle import ContentLifecycleService
            from .publishing.dry_run import DryRunPublisher

            # Ensure the pipeline (and its queue) exist, then share the queue.
            self._pipeline()
            self._content_lifecycle = ContentLifecycleService(
                queue=self._content_queue_repo,
                publisher=DryRunPublisher(),
            )
        return self._content_lifecycle

    def approve_content(self, content_id: str) -> Optional[Dict[str, Any]]:
        if self._content_queue_repo.get(content_id) is None:
            return None
        return self._lifecycle().approve_review(content_id).to_dict()

    def reject_content(
        self, content_id: str, reason: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        if self._content_queue_repo.get(content_id) is None:
            return None
        return self._lifecycle().reject_review(content_id, reason).to_dict()

    def schedule_content(self, content_id: str) -> Optional[Dict[str, Any]]:
        if self._content_queue_repo.get(content_id) is None:
            return None
        return self._lifecycle().schedule(content_id).to_dict()

    def publish_content(self, content_id: str) -> Optional[Dict[str, Any]]:
        if self._content_queue_repo.get(content_id) is None:
            return None
        return self._lifecycle().publish(content_id).to_dict()

    # ------------------------------------------------------------ system status
    def system_status(self) -> Dict[str, Any]:
        try:
            counts = self._entity_counts()
            freshness = self._data_freshness()
            pending = self._pending_events()
            return {
                "status": "ok",
                "counts": counts,
                "freshness": freshness,
                "pending_events": pending,
            }
        except Exception as exc:  # noqa: BLE001 - status must never raise
            return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}

    def _entity_counts(self) -> Dict[str, int]:
        raise NotImplementedError

    def _data_freshness(self) -> Dict[str, Any]:
        raise NotImplementedError

    def _pending_events(self) -> int:
        raise NotImplementedError

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
            SqliteMatchStatsRepository,
            SqlitePlayerRepository,
            SqlitePublicationRepository,
            SqliteRatingRepository,
            SqliteStandingRepository,
            SqliteTeamRepository,
        )

        from .persistence.content_queue_repo import SqliteContentQueueRepository

        return {
            "idempotency": SqliteIdempotencyRepository(self.db),
            "match": SqliteMatchRepository(self.db),
            "stats": SqliteMatchStatsRepository(self.db),
            "player": SqlitePlayerRepository(self.db),
            "team": SqliteTeamRepository(self.db),
            "competition": SqliteCompetitionRepository(self.db),
            "correction": SqliteCorrectionRepository(self.db),
            "standing": SqliteStandingRepository(self.db),
            "leaderboard": SqliteLeaderboardRepository(self.db),
            "rating": SqliteRatingRepository(self.db),
            "publication": SqlitePublicationRepository(self.db),
            "content_queue": SqliteContentQueueRepository(self.db),
        }

    def _entity_counts(self) -> Dict[str, int]:
        conn = self.db.connect()
        try:
            counts = {}
            for table in ("matches", "players", "teams", "player_stats", "team_stats"):
                row = conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()  # noqa: S608
                counts[table] = row[0] if isinstance(row, (list, tuple)) else row["c"]
            return counts
        finally:
            conn.close()

    def _data_freshness(self) -> Dict[str, Any]:
        conn = self.db.connect()
        try:
            row = conn.execute(
                "SELECT data FROM matches ORDER BY json_extract(data, '$.scheduled_at') DESC LIMIT 1"
            ).fetchone()
            if row is None:
                return {"latest_match_scheduled_at": None, "total_seasons": 0}
            import json as _json
            data = _json.loads(row[0] if isinstance(row, (list, tuple)) else row["data"])
            seasons = conn.execute("SELECT COUNT(DISTINCT season_code) AS c FROM matches").fetchone()
            season_count = seasons[0] if isinstance(seasons, (list, tuple)) else seasons["c"]
            return {
                "latest_match_scheduled_at": data.get("scheduled_at"),
                "total_seasons": season_count,
            }
        finally:
            conn.close()

    def _pending_events(self) -> int:
        store = self.db.event_store()
        return store.pending_count()

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
            PgMatchStatsRepository,
            PgPlayerRepository,
            PgPublicationRepository,
            PgRatingRepository,
            PgStandingRepository,
            PgTeamRepository,
        )

        from .persistence.content_queue_repo import PgContentQueueRepository

        return {
            "idempotency": PgIdempotencyRepository(self.db),
            "match": PgMatchRepository(self.db),
            "stats": PgMatchStatsRepository(self.db),
            "player": PgPlayerRepository(self.db),
            "team": PgTeamRepository(self.db),
            "competition": PgCompetitionRepository(self.db),
            "correction": PgCorrectionRepository(self.db),
            "standing": PgStandingRepository(self.db),
            "leaderboard": PgLeaderboardRepository(self.db),
            "rating": PgRatingRepository(self.db),
            "publication": PgPublicationRepository(self.db),
            "content_queue": PgContentQueueRepository(self.db),
        }

    def _entity_counts(self) -> Dict[str, int]:
        conn = self.db.connect()
        try:
            counts = {}
            for table in ("matches", "players", "teams", "player_stats", "team_stats"):
                row = conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()  # noqa: S608
                counts[table] = row["c"]
            return counts
        finally:
            conn.close()

    def _data_freshness(self) -> Dict[str, Any]:
        conn = self.db.connect()
        try:
            row = conn.execute(
                "SELECT data::text AS data FROM matches"
                " ORDER BY (data->>'scheduled_at') DESC NULLS LAST LIMIT 1"
            ).fetchone()
            if row is None:
                return {"latest_match_scheduled_at": None, "total_seasons": 0}
            import json as _json
            data = _json.loads(row["data"])
            seasons = conn.execute("SELECT COUNT(DISTINCT season_code) AS c FROM matches").fetchone()
            return {
                "latest_match_scheduled_at": data.get("scheduled_at"),
                "total_seasons": seasons["c"],
            }
        finally:
            conn.close()

    def _pending_events(self) -> int:
        store = self.db.event_store()
        return store.pending_count()

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