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

import os
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
        self._image_override_repo = repos["image_override"]
        self._media_asset_repo = repos["media_asset"]
        self._content_pipeline: Optional[RoundPipeline] = None
        self._content_lifecycle = None  # lazily built alongside the pipeline
        # Ephemeral preview cache: cards the operator has seen from Ideas but
        # not yet sent to the real queue. Lives one process; TTL 30 min.
        from ..application.use_cases.preview_store import PreviewStore
        self._preview_store = PreviewStore()

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
            # Bio (public profile): absent fields stay null — never invented.
            "position": player.position,
            "height_cm": player.height_cm,
            "birth_date": player.birth_date.isoformat() if player.birth_date else None,
            "birth_place": player.birth_place,
            "nationality": player.nationality,
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
            from .rendering.feb_image_assets import FebImageAssetProvider
            from .rendering.svg_renderer import ComponentSvgRenderer

            # Official FEB portraits/crests, falling back to initials per asset.
            # Rendering therefore touches the network: the provider caches, times
            # out, and trips a circuit breaker, but FEB_SCORE_OFFICIAL_IMAGES=0 is
            # the kill switch if that host ever becomes a problem — no deploy
            # needed to go back to the purely statistical identity.
            official_images = os.environ.get(
                "FEB_SCORE_OFFICIAL_IMAGES", "true"
            ).strip().lower() not in {"0", "false", "no"}
            base_assets = (
                FebImageAssetProvider() if official_images
                else StatisticalAssetProvider()
            )
            # Asset chain, highest precedence first: media library (multi-photo
            # + rights) beats the legacy single-slot operator override, which
            # beats FEB / statistical initials. New uploads land in the media
            # library; the override endpoints stay live so nothing shipped
            # before this stops working.
            from .rendering.override_assets import (
                MediaAssetProvider,
                OverrideAssetProvider,
            )
            assets = OverrideAssetProvider(self._image_override_repo, base_assets)
            assets = MediaAssetProvider(self._media_asset_repo, assets)

            self._content_pipeline = RoundPipeline(
                renderer=ComponentSvgRenderer(),
                assets=assets,
                queue=self._content_queue_repo,
                design_system_version=DESIGN_SYSTEM_VERSION,
            )
        return self._content_pipeline

    def _content_inputs(self, season_code: str, round_number: int):
        inputs = self._content_adapter.build_round_inputs(season_code, round_number)
        return (
            inputs,
            self._content_adapter.build_season_context(season_code, round_number, inputs),
            self._content_adapter.build_season_aggregate(season_code),
            self._content_adapter.build_league_bio(season_code),
        )

    def preview_round_candidates(
        self, season_code: str, round_number: int
    ) -> Dict[str, Any]:
        inputs, season_context, season_aggregate, league_bio = self._content_inputs(
            season_code, round_number
        )
        candidates = self._pipeline().detect_candidates(
            inputs.season_code, inputs.round_number,
            inputs.matches, inputs.player_lines,
            season_context=season_context, season=season_aggregate, bio=league_bio,
        )
        return {
            "season_code": season_code,
            "round_number": round_number,
            "matches_considered": len(inputs.matches),
            "candidates": candidates,
        }

    def run_content_pipeline(
        self, season_code: str, round_number: int, top_n: int = 5,
        story_keys: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        inputs, season_context, season_aggregate, league_bio = self._content_inputs(
            season_code, round_number
        )
        pipeline = self._pipeline()
        result = pipeline.run(
            inputs.season_code,
            inputs.round_number,
            inputs.matches,
            inputs.player_lines,
            top_n=top_n,
            season_context=season_context,
            season=season_aggregate,
            bio=league_bio,
            only_keys=story_keys,
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

    def _lookup_item(self, content_id: str):
        """Queue first, ephemeral PreviewStore as fallback. Lets the same
        render.png URL serve a card whether the operator has committed it or
        is still deciding."""
        item = self._pipeline().queue.get(content_id)
        if item is not None:
            return item
        return self._preview_store.get(content_id)

    def get_content_item(self, content_id: str) -> Optional[Dict[str, Any]]:
        item = self._lookup_item(content_id)
        return item.to_dict() if item is not None else None

    def render_content_item(self, content_id: str) -> Optional[str]:
        """The item's SVG, made self-contained. Reads from the queue or the
        ephemeral preview store so a not-yet-committed card still renders.

        Cards are STORED with references to the shared assets (the background
        alone was 96% of a 1.85 MB card, identical in every row); they are
        expanded here so what leaves the API still stands on its own.
        """
        from .rendering.component_templates import inline_shared_assets

        item = self._lookup_item(content_id)
        if item is None or item.rendered_svg is None:
            return None
        return inline_shared_assets(item.rendered_svg)

    def render_content_item_png(
        self, content_id: str, width: int, height: int
    ) -> Optional[bytes]:
        """The publishable image. Goes through render_content_item so the
        assets are inlined first — the rasteriser resolves nothing off disk, so
        an un-inlined card would come out with holes where the court is."""
        from ..api.gateway import ImageRenderingFailed, ImageRenderingUnavailable
        from .rendering.rasterizer import (
            RasterizationFailed,
            RasterizerUnavailable,
            rasterize_png,
        )

        svg = self.render_content_item(content_id)
        if svg is None:
            return None
        try:
            return rasterize_png(svg, width=width, height=height)
        except RasterizerUnavailable as exc:
            raise ImageRenderingUnavailable(str(exc)) from exc
        except RasterizationFailed as exc:
            raise ImageRenderingFailed(str(exc)) from exc

    # ------------------------------------------------------------ explorer
    EXPLORE_METRICS = ("points", "rebounds", "assists", "steals", "blocks",
                       "turnovers", "minutes", "games_played")

    @staticmethod
    def _season_reference_date(season_code: str):
        """The date ages are measured at: the end of the season's second year.

        A season spans two calendar years, so "how old was he" needs a fixed
        point or the answer drifts every day. The season's April is close enough
        to the end of the competition to describe the whole year honestly, and
        it is deterministic — the same query gives the same ages tomorrow.
        """
        from datetime import date
        tail = season_code.split("-")[-1]
        try:
            return date(int(tail), 4, 30)
        except (TypeError, ValueError):
            return None

    SMOKE_SEASON = "0000-0000"

    def list_seasons(self) -> List[Dict[str, Any]]:
        """Every season with matches, newest first. Derived from the matches
        table, so a season shows up as soon as it has a single fixture — which
        is what the dropdowns want: pick from what actually exists, no typing.
        """
        # The deploy smoke test writes one match per deploy into the throwaway
        # season 0000-0000, so it would otherwise show up as a pickable season in
        # every operator dropdown. It is not a real season — hide it.
        return [
            {"season_code": code, "matches": count}
            for code, count in self._match_repo.list_seasons()
            if code != self.SMOKE_SEASON
        ]

    def season_insights(self, season_code: str) -> Dict[str, Any]:
        """Discovery signals a season aggregate can't give: the best SINGLE-GAME
        performances (records), the double-double leaders, and who is trending
        up (recent FEB vs season FEB). All from the per-game lines; nothing
        invented — a game with no rateable line simply does not contribute.
        """
        from collections import defaultdict
        from datetime import datetime
        from ..domain.statistics.metrics import valoracion
        from ..domain.content.rating import feb_rating

        season = SeasonCode(season_code)
        lines = list(self._stats_repo.list_season_player_lines(season))
        ids = {l.player_external_id for l in lines}
        catalog = self._player_repo.get_many_by_external_ids(ids)
        player_team = self._stats_repo.list_season_player_teams(season)
        tnames = {tid: rec.name for tid, rec in
                  self._team_repo.get_many_by_external_ids(set(player_team.values())).items()
                  if rec is not None}

        def nm(pid):
            rec = catalog.get(pid)
            return (rec.name if rec is not None else None) or pid

        def tm(pid):
            tid = player_team.get(pid)
            return tnames.get(tid) if tid else None

        def feb_of(l):
            return feb_rating(
                l.points, l.rebounds, l.assists, l.steals, l.blocks, l.turnovers,
                minutes=l.minutes, field_goals_made=l.field_goals_made,
                field_goals_attempted=l.field_goals_attempted,
                free_throws_made=l.free_throws_made or 0,
                free_throws_attempted=l.free_throws_attempted or 0,
                three_points_made=l.three_points_made or 0,
                fouls=l.fouls or 0, fouls_received=l.fouls_received or 0)

        def entry(l, value):
            return {"player": nm(l.player_external_id),
                    "player_external_id": l.player_external_id,
                    "team": tm(l.player_external_id), "value": value,
                    "line": {"points": l.points, "rebounds": l.rebounds,
                             "assists": l.assists}}

        records = []
        if lines:
            for key, label in (("points", "Puntos"), ("rebounds", "Rebotes"),
                               ("assists", "Asistencias"), ("steals", "Robos"),
                               ("blocks", "Tapones")):
                best = max(lines, key=lambda l: getattr(l, key))
                records.append({"metric": key, "label": label,
                                **entry(best, getattr(best, key))})
            vals = [(l, valoracion(l)) for l in lines]
            vals = [(l, v) for l, v in vals if v is not None]
            if vals:
                bl, bv = max(vals, key=lambda t: t[1])
                records.append({"metric": "val", "label": "Valoración", **entry(bl, bv)})
            febs = [(l, feb_of(l)) for l in lines]
            febs = [(l, v) for l, v in febs if v is not None]
            if febs:
                bl, bv = max(febs, key=lambda t: t[1])
                records.append({"metric": "feb", "label": "FEB Rating",
                                **entry(bl, round(bv, 1))})

        # double-doubles / triple-doubles
        def dd(l):
            return sum(1 for x in (l.points, l.rebounds, l.assists, l.steals, l.blocks) if x >= 10)
        dd_count = defaultdict(int)
        td_total = 0
        for l in lines:
            c = dd(l)
            if c >= 2:
                dd_count[l.player_external_id] += 1
            if c >= 3:
                td_total += 1
        double_doubles = [
            {"player": nm(p), "player_external_id": p, "team": tm(p), "count": c}
            for p, c in sorted(dd_count.items(), key=lambda kv: (-kv[1], kv[0]))[:8]
        ]

        # form: last-3 FEB vs season FEB (min 6 rateable games)
        by_player = defaultdict(list)
        for l in lines:
            by_player[l.player_external_id].append(l)
        form = []
        for pid, pls in by_player.items():
            ordered = sorted(pls, key=lambda l: (l.played_at or datetime.min))
            fseq = [f for f in (feb_of(l) for l in ordered) if f is not None]
            if len(fseq) < 6:
                continue
            season_avg = sum(fseq) / len(fseq)
            last3 = sum(fseq[-3:]) / 3
            form.append({"player": nm(pid), "player_external_id": pid, "team": tm(pid),
                         "last3": round(last3, 1), "season": round(season_avg, 1),
                         "delta": round(last3 - season_avg, 1)})
        form.sort(key=lambda f: (-f["delta"], f["player"]))

        # STRICT streaks: the longest run of CONSECUTIVE games meeting a
        # condition, per player (games ordered by date). A count of games is not
        # a streak — these are runs that were never broken.
        def longest_run(pls, cond):
            ordered = sorted(pls, key=lambda l: (l.played_at or datetime.min))
            run = best = 0
            for l in ordered:
                run = run + 1 if cond(l) else 0
                best = max(best, run)
            return best

        def streaks(cond, floor):
            out = []
            for pid, pls in by_player.items():
                run = longest_run(pls, cond)
                if run >= floor:
                    out.append({"player": nm(pid), "player_external_id": pid,
                                "team": tm(pid), "count": run})
            out.sort(key=lambda x: (-x["count"], x["player"]))
            return out[:6]

        streaks_dd = streaks(lambda l: dd(l) >= 2, 2)
        streaks_scoring = streaks(lambda l: l.points >= 20, 3)

        return {"season_code": season_code, "records": records,
                "double_doubles": double_doubles, "triple_doubles_total": td_total,
                "form_up": form[:6],
                "streaks_dd": streaks_dd, "streaks_scoring": streaks_scoring}

    def generate_round_recap(self, season_code: str, round_number: int) -> Dict[str, Any]:
        """Generate ONLY the round-recap card for a round, straight from the
        Explorer. Reuses the pipeline: detect the round's candidates, pick the
        round_recap, and run exactly that one — same validation and dedup as any
        other card. Nothing invented; a round with no recap yields no card."""
        preview = self.preview_round_candidates(season_code, round_number)
        recap = next((c for c in preview.get("candidates", [])
                      if c.get("story_type") == "round_recap"), None)
        if recap is None:
            raise ValueError("no hay round recap para esa jornada (sin datos suficientes)")
        result = self.run_content_pipeline(
            season_code, round_number, story_keys=[recap["story_key"]])
        items = result.get("items", [])
        if items:
            it = items[0]
            return {"created": True, "status": it["status"],
                    "content_id": it["content_id"], "round_number": round_number}
        return {"created": False,
                "status": "already_queued" if recap.get("already_queued") else "none",
                "round_number": round_number}

    def explore_players(
        self, season_code: str, *,
        team: Optional[str] = None, nationality: Optional[str] = None,
        position: Optional[str] = None, min_age: Optional[int] = None,
        max_age: Optional[int] = None, min_games: Optional[int] = None,
        metric: str = "points", per_game: bool = False, limit: int = 25,
    ) -> Dict[str, Any]:
        """Free-form search over a season's players — the hunting ground for
        custom content. Read-only: it never writes and never invents, it just
        joins what is already stored (stats + catalog + bio + team)."""
        if metric not in self.EXPLORE_METRICS:
            raise ValueError(
                f"metric must be one of {', '.join(self.EXPLORE_METRICS)}")

        season = SeasonCode(season_code)
        aggregates = list(self._stats_repo.list_season_player_aggregates(season))
        if not aggregates:
            # Same envelope shape as a populated answer: the page reads the
            # keys unconditionally.
            return {"season_code": season_code, "metric": metric,
                    "per_game": per_game, "count": 0, "rows": [],
                    "facets": {"teams": [], "nationalities": [], "positions": []}}

        ids = {a.player_external_id for a in aggregates}
        catalog = self._player_repo.get_many_by_external_ids(ids)
        player_team = self._stats_repo.list_season_player_teams(season)
        team_catalog = self._team_repo.get_many_by_external_ids(set(player_team.values()))
        team_names = {tid: rec.name for tid, rec in team_catalog.items()
                      if rec is not None}
        bio = self._content_adapter.build_league_bio(season_code)
        ref = self._season_reference_date(season_code)
        # Same resolution order the renderer uses: an operator override wins
        # over the FEB photo, so the explorer shows the face a card would.
        from .rendering.feb_image_assets import PLAYER_PHOTO_URL
        overrides = self._image_override_repo.list_meta()
        # Media DB status per player (the render path already respects the
        # licence via select(); this is the discreet at-a-glance indicator).
        from collections import defaultdict as _dd
        media_by = _dd(list)
        for m in self._media_asset_repo.list_meta("player"):
            media_by[m.external_id].append(m)

        def photo_status(pid):
            if ("player", pid) in overrides:
                return "approved"        # an operator image, already usable
            ms = media_by.get(pid)
            if ms and any(m.approved for m in ms):
                return "approved"
            if ms:
                return "pending"         # material exists but nothing approved
            return "none"

        # Season FEB Rating (average of the per-game notes) and VAL (official
        # valuation, summed) — derived from the per-game blobs, which carry the
        # shooting the column aggregate lacks. Never invented: a game with no
        # shooting data yields no note and no valuation.
        from collections import defaultdict
        from ..domain.statistics.metrics import valoracion
        from ..domain.content.rating import feb_rating
        feb_sum: Dict[str, float] = defaultdict(float)
        feb_n: Dict[str, int] = defaultdict(int)
        val_sum: Dict[str, int] = defaultdict(int)
        val_n: Dict[str, int] = defaultdict(int)
        for line in self._stats_repo.list_season_player_lines(season):
            lpid = line.player_external_id
            v = valoracion(line)
            if v is not None:
                val_sum[lpid] += v; val_n[lpid] += 1
            r = feb_rating(
                line.points, line.rebounds, line.assists, line.steals,
                line.blocks, line.turnovers, minutes=line.minutes,
                field_goals_made=line.field_goals_made,
                field_goals_attempted=line.field_goals_attempted,
                free_throws_made=line.free_throws_made or 0,
                free_throws_attempted=line.free_throws_attempted or 0,
                three_points_made=line.three_points_made or 0,
                fouls=line.fouls or 0, fouls_received=line.fouls_received or 0)
            if r is not None:
                feb_sum[lpid] += r; feb_n[lpid] += 1

        rows: List[Dict[str, Any]] = []
        for a in aggregates:
            pid = a.player_external_id
            rec = catalog.get(pid)
            tid = player_team.get(pid)
            games = a.games_played or 0
            row = {
                "player_external_id": pid,
                "name": (rec.name if rec is not None else None) or pid,
                "team_external_id": tid,
                "team_name": team_names.get(tid) if tid else None,
                "nationality": bio.nationality(pid),
                "position": bio.position(pid),
                "age": bio.age_on(pid, ref) if ref else None,
                "games_played": games,
                "points": a.points, "rebounds": a.rebounds, "assists": a.assists,
                "steals": a.steals, "blocks": a.blocks, "turnovers": a.turnovers,
                "minutes": a.minutes,
                # season VAL total (official valuation, summed) and FEB Rating
                # (average of the game notes); None when unavailable, never 0.
                "val": val_sum.get(pid) if val_n.get(pid) else None,
                "feb": round(feb_sum[pid] / feb_n[pid], 1) if feb_n.get(pid) else None,
                "photo_status": photo_status(pid),
                "image_url": (f"/v1/images/player/{pid}"
                              if ("player", pid) in overrides
                              else PLAYER_PHOTO_URL.format(player_external_id=pid)),
            }
            rows.append(row)

        # Facets come from the WHOLE season, not the filtered set, so the
        # dropdowns do not shrink as you narrow the search.
        facets = {
            "teams": sorted({(r["team_external_id"], r["team_name"] or r["team_external_id"])
                             for r in rows if r["team_external_id"]},
                            key=lambda t: (t[1] or "").lower()),
            "nationalities": sorted({r["nationality"] for r in rows if r["nationality"]}),
            "positions": sorted({r["position"] for r in rows if r["position"]}),
        }

        def keep(r: Dict[str, Any]) -> bool:
            if team and r["team_external_id"] != team:
                return False
            if nationality and r["nationality"] != nationality:
                return False
            if position and r["position"] != position:
                return False
            if min_games is not None and r["games_played"] < min_games:
                return False
            if min_age is not None and (r["age"] is None or r["age"] < min_age):
                return False
            if max_age is not None and (r["age"] is None or r["age"] > max_age):
                return False
            return True

        rows = [r for r in rows if keep(r)]
        for r in rows:
            raw = r.get(metric) or 0
            # Per-game needs games; a player with none is not ranked on an
            # average that would be a division by zero dressed as a number.
            r["value"] = round(raw / r["games_played"], 1) if (
                per_game and r["games_played"]) else raw
        rows.sort(key=lambda r: (-(r["value"] or 0), r["name"].lower()))

        return {
            "season_code": season_code,
            "metric": metric,
            "per_game": per_game,
            "count": len(rows),
            "rows": rows[:limit],
            "facets": {
                "teams": [{"external_id": i, "name": n} for i, n in facets["teams"]],
                "nationalities": facets["nationalities"],
                "positions": facets["positions"],
            },
        }

    # A metric's own name, for the column header on the card. The card is in
    # Spanish; the API parameter is not, so the two are mapped in one place.
    METRIC_LABELS = {
        "points": "PUNTOS", "rebounds": "REBOTES", "assists": "ASISTENCIAS",
        "steals": "ROBOS", "blocks": "TAPONES", "turnovers": "PÉRDIDAS",
        "minutes": "MINUTOS", "games_played": "PARTIDOS",
    }
    PG_LABELS = {
        "points": "PPP", "rebounds": "RPP", "assists": "APP", "steals": "ROB/P",
        "blocks": "TAP/P", "turnovers": "PER/P", "minutes": "MIN/P", "games_played": "PJ",
    }
    CUSTOM_FIVE_SIZE = 5

    _HERO_BADGE = {
        "points": "ANOTADOR", "rebounds": "REBOTEADOR",
        "assists": "ASISTENTE", "steals": "ROBO",
        "blocks": "TAPÓN", "turnovers": "PÉRDIDAS",
        "minutes": "MINUTOS", "games_played": "PARTIDOS",
    }

    _HERO_KINDS = ("average", "total", "peak")

    def create_stat_hero(
        self, season_code: str, *, player_id: str, metric: str = "points",
        per_game: bool = False, title: str, subtitle: Optional[str] = None,
        scope_label: Optional[str] = None, hero_style: str = "crest",
        hero_kind: Optional[str] = None, force: bool = False,
        pending: bool = False, preview: bool = False,
    ) -> Dict[str, Any]:
        """One player as a single hero card, built from a query. Two visual
        variants share the same facts: ``crest`` (photo-less, crest silhouette
        identity) and ``photo`` (player photo as the centrepiece). The caller
        sends the player, the words, and the style; the figures are re-read
        here, never posted by the client.

        ``hero_kind`` decides what number is the protagonist:
          * ``average`` — season total / games (also the default when per_game).
          * ``total``   — season aggregate.
          * ``peak``    — the SINGLE-GAME peak for that metric. This is what
            a "récord de la temporada" is really claiming; without it, a card
            built from a records row would render the season average, and the
            claim on the card would not match what the operator picked.
        """
        from ..domain.content.story import StoryObject, StoryEntities, StoryType

        title = (title or "").strip()
        if not title:
            raise ValueError("title is required")
        if metric not in self.EXPLORE_METRICS:
            raise ValueError(f"metric must be one of {', '.join(self.EXPLORE_METRICS)}")
        if hero_style not in ("crest", "photo", "split"):
            raise ValueError("hero_style must be 'crest', 'photo' or 'split'")
        # Default hero_kind: whatever per_game said (backwards-compatible).
        if hero_kind is None:
            hero_kind = "average" if per_game else "total"
        if hero_kind not in self._HERO_KINDS:
            raise ValueError(f"hero_kind must be one of {', '.join(self._HERO_KINDS)}")
        row = next((r for r in self.explore_players(season_code, limit=600)["rows"]
                    if r["player_external_id"] == player_id), None)
        if row is None:
            raise ValueError("that player has no data in the season")
        total = row.get(metric)
        if total is None:
            raise ValueError("no data for that metric")
        games = row["games_played"] or 0
        per = round(total / games, 1) if games else 0.0
        label = self.METRIC_LABELS.get(metric, metric.upper())

        # ``peak`` means "the best single game", not the season aggregate — the
        # detector reads the per-game lines and finds the max for the metric so
        # the card claims a number that actually happened in one game. When we
        # can, we also compute THAT game's FEB Rating so the on-card note
        # matches the single-game moment, not a diluted season average.
        peak_value = None
        peak_feb: Optional[float] = None
        if hero_kind == "peak":
            from ..domain.value_objects import SeasonCode
            from ..domain.content.rating import feb_rating as _peak_feb_rating
            lines = list(self._stats_repo.list_player_stats_by_season(
                player_id, SeasonCode(season_code)))
            if lines:
                peak_line = max(lines, key=lambda l: getattr(l, metric, 0))
                peak_value = getattr(peak_line, metric, 0)
                try:
                    peak_feb = _peak_feb_rating(
                        peak_line.points, peak_line.rebounds, peak_line.assists,
                        peak_line.steals, peak_line.blocks, peak_line.turnovers,
                        minutes=peak_line.minutes,
                        field_goals_made=peak_line.field_goals_made,
                        field_goals_attempted=peak_line.field_goals_attempted,
                        free_throws_made=peak_line.free_throws_made or 0,
                        free_throws_attempted=peak_line.free_throws_attempted or 0,
                        three_points_made=peak_line.three_points_made or 0,
                        fouls=peak_line.fouls or 0,
                        fouls_received=peak_line.fouls_received or 0,
                    )
                except Exception:  # noqa: BLE001 — rating is decorative here
                    peak_feb = None
            if not peak_value:
                raise ValueError("no per-game data for that metric")

        if hero_kind == "peak":
            hero_value_raw = peak_value
            hero_label = f"{label} EN UN PARTIDO"
        elif hero_kind == "average":
            hero_value_raw = per
            hero_label = f"{label} POR PARTIDO"
        else:  # total
            hero_value_raw = total
            hero_label = label if metric in ("games_played",) else f"{label} TOTALES"

        kicker = scope_label or f"Temporada {season_code[:4]}-{season_code[-2:]}"
        # Supporting stats: for total/average cards the games + per-game frame
        # the aggregate; for a peak card the frame is "here's the peak, and this
        # is the season it sits inside" (games + season average).
        secondary = (
            [[games, "PART"], [self._es_number(per), "MEDIA"]]
            if hero_kind == "peak"
            else [[games, "PART"], [self._es_number(per), self.PG_LABELS.get(metric, "/P")]]
        )
        badge = "RÉCORD" if hero_kind == "peak" else self._HERO_BADGE.get(metric, label)
        facts = {
            "section_label": title, "subtitle": subtitle or "",
            "hero_value": self._es_number(hero_value_raw),
            "hero_label": hero_label,
            "secondary": secondary,
            # For a peak card use THAT game's FEB Rating when we can compute
            # it; a season average glued onto a single-game record would tell
            # a different story than the number above it.
            "rating": (peak_feb if hero_kind == "peak" and peak_feb is not None
                       else row.get("feb")),
            "kicker": kicker.upper(),
            "player_name": row["name"], "team_name": row["team_name"],
            "team_external_id": row["team_external_id"], "player_external_id": player_id,
            "points": row["points"], "rebounds": row["rebounds"], "assists": row["assists"],
            # Visual variant + a short qualifier for the photo layout's chip. The
            # crest renderer ignores badge_label; the photo one uses it so the
            # portrait carries context beyond the number.
            "hero_style": hero_style,
            "hero_kind": hero_kind,
            "badge_label": badge,
        }
        # Split variant renders on the player_streak template, which asks for
        # streak_length + streak_kind in its slot contract. This card isn't a
        # streak, but it uses the same visual, so mirror the SEASON_DD_LEADER
        # trick: satisfy the contract with a "custom" kind and the hero value
        # as the length. The renderer reads facts.hero_value first, so nothing
        # on screen changes.
        if hero_style == "split":
            facts["streak_length"] = hero_value_raw
            facts["streak_kind"] = "custom"
        story = StoryObject(
            story_type=StoryType.CUSTOM_HERO, season_code=season_code, round_number=None,
            entities=StoryEntities(player_external_id=player_id,
                                   team_external_id=row["team_external_id"]),
            facts=facts,
            source_refs={"season_player_stats":
                         f"2afeb_score://season_player_stats/{season_code}/{player_id}"})
        item = self._pipeline().generate_one(
            story, force=force, force_review=pending, persist=not preview)
        if preview and item.status not in ("rejected", "failed"):
            self._preview_store.put(item)
        return item.to_dict()

    def create_season_dd_leader_card(
        self, season_code: str, *, force: bool = False, pending: bool = False,
        preview: bool = False,
    ) -> Dict[str, Any]:
        """Season retrospective: the player with the most double-doubles this
        year, with their triple-double count riding as the extras line. All
        figures re-read here from the per-game store; nothing invented, nothing
        posted by the caller. Fails cleanly when the season has no DDs yet.
        """
        from collections import defaultdict
        from ..domain.content.story import StoryObject, StoryEntities, StoryType
        from ..domain.value_objects import SeasonCode

        season = SeasonCode(season_code)
        lines = list(self._stats_repo.list_season_player_lines(season))
        if not lines:
            raise ValueError("no player lines for that season")

        def _kinds(l):
            return sum(1 for x in (l.points, l.rebounds, l.assists, l.steals, l.blocks)
                       if x >= 10)
        dd: Dict[str, int] = defaultdict(int)
        td: Dict[str, int] = defaultdict(int)
        for l in lines:
            n = _kinds(l)
            if n >= 2:
                dd[l.player_external_id] += 1
            if n >= 3:
                td[l.player_external_id] += 1

        if not dd:
            raise ValueError("no double-doubles in this season yet")
        leader_id = max(dd, key=lambda pid: (dd[pid], td.get(pid, 0)))
        leader_dd = dd[leader_id]
        leader_td = td.get(leader_id, 0)

        player = self._player_repo.get_by_external_id(leader_id)
        player_name = player.name if player is not None else leader_id
        player_teams = self._stats_repo.list_season_player_teams(season)
        team_id = player_teams.get(leader_id, "")
        team = self._team_repo.get_by_external_id(team_id) if team_id else None
        team_name = team.name if team is not None else team_id

        year1, year2 = season_code[:4], season_code[-2:]
        extras = ""
        if leader_td:
            extras = f"+{leader_td} triple-doble{'s' if leader_td != 1 else ''}"

        facts = {
            "hero_value": leader_dd,
            "hero_label": "DOBLES-DOBLES",
            "section_label": "MÁS DOBLES-DOBLES DE LA TEMPORADA",
            "extras_label": extras,
            "kicker": f"TEMPORADA {year1}-{year2}",
            # Satisfy the player_streak template contract (streak_length +
            # streak_kind). Kind marks this row as a season TOTAL, not an
            # active or peak consecutive run.
            "streak_kind": "double_double_total",
            "streak_length": leader_dd,
            "dd_count": leader_dd,
            "td_count": leader_td,
            "player_external_id": leader_id, "player_name": player_name,
            "team_external_id": team_id, "team_name": team_name,
        }
        story = StoryObject(
            story_type=StoryType.SEASON_DD_LEADER,
            season_code=season_code, round_number=None,
            entities=StoryEntities(
                player_external_id=leader_id, team_external_id=team_id),
            facts=facts,
            source_refs={
                "season_player_stats":
                    f"2afeb_score://season_player_stats/{season_code}",
            },
        )
        item = self._pipeline().generate_one(
            story, force=force, force_review=pending, persist=not preview)
        if preview and item.status not in ("rejected", "failed"):
            self._preview_store.put(item)
        return item.to_dict()

    def create_custom_five(
        self, season_code: str, *, title: str, subtitle: str = "",
        scope_label: Optional[str] = None, player_ids: Optional[List[str]] = None,
        show_rank: bool = True, force: bool = False, pending: bool = False,
        preview: bool = False,
        **query: Any
    ) -> Dict[str, Any]:
        """Turn an explorer query into a card.

        The caller sends the QUERY and the words, never the numbers: the rows
        are re-read here through ``explore_players``, the same path that drew
        them on screen. A client that could post its own figures would be a
        hole straight through the no-invention rule, so there is no parameter
        for one.

        ``player_ids`` narrows the result to a hand-picked few (still ranked by
        the query's metric); without it the top five of the query are taken.
        """
        from ..domain.content.story import StoryObject, StoryEntities, StoryType

        title = (title or "").strip()
        if not title:
            raise ValueError("title is required")

        # Ask for more than five when the operator is picking by hand, so their
        # choice is not silently cut off by the ranking.
        query.pop("limit", None)
        result = self.explore_players(season_code, limit=200, **query)
        rows = result["rows"]
        if player_ids:
            wanted = list(dict.fromkeys(player_ids))
            by_id = {r["player_external_id"]: r for r in rows}
            missing = [p for p in wanted if p not in by_id]
            if missing:
                raise ValueError(
                    "these players are not in the query result: " + ", ".join(missing))
            # Kept in the QUERY's order, not the order they were ticked in: the
            # card numbers its rows, and a 20-steal player sitting above a
            # 45-steal one under a "1" would be a ranking that lies.
            chosen = set(wanted)
            rows = [r for r in rows if r["player_external_id"] in chosen]
        rows = rows[: self.CUSTOM_FIVE_SIZE]
        if not rows:
            raise ValueError("the query matched no players, so there is no card")

        metric = result["metric"]
        per_game = result["per_game"]
        label = self.METRIC_LABELS.get(metric, metric.upper())
        metric_label = f"{label} POR PARTIDO" if per_game else label

        lineup = [
            {
                "rank": i,
                "player_external_id": r["player_external_id"],
                "player_name": r["name"],
                "team_external_id": r["team_external_id"],
                "team_name": r["team_name"],
                "points": r["points"], "rebounds": r["rebounds"],
                "assists": r["assists"],
                "value": self._es_number(r["value"]),
                "context": self._custom_context(r, metric, per_game=per_game),
            }
            for i, r in enumerate(rows, start=1)
        ]
        facts = {
            "lineup": lineup,
            "count": len(lineup),
            "title": title,
            "subtitle": subtitle or self._custom_subtitle(query, result["facets"]),
            "scope_label": scope_label or season_code,
            "count_label": f"Top {len(lineup)}",
            "metric_label": metric_label,
            "metric": metric,
            "per_game": per_game,
            "show_rank": show_rank,
            "filters": {k: v for k, v in query.items() if v not in (None, "")},
        }
        story = StoryObject(
            story_type=StoryType.CUSTOM_FIVE,
            season_code=season_code,
            round_number=None,          # a query is not a round
            entities=StoryEntities(),
            facts=facts,
            source_refs={
                "season_player_aggregates":
                    f"2afeb_score://season_player_aggregates/{season_code}",
            },
        )
        item = self._pipeline().generate_one(
            story, force=force, force_review=pending, persist=not preview)
        if preview and item.status not in ("rejected", "failed"):
            self._preview_store.put(item)
        return item.to_dict()

    @staticmethod
    def _es_number(value: Any) -> str:
        """The cards are written in Spanish: 12,4 — never 12.4."""
        if isinstance(value, float):
            return f"{value:.1f}".replace(".", ",")
        return str(value)

    @staticmethod
    def _custom_subtitle(query: Dict[str, Any], facets: Dict[str, Any]) -> str:
        """WHO was eligible, in words — the honest framing of any filtered
        ranking, and the one thing the card does not say anywhere else. It
        deliberately does NOT restate the metric: that is the column header.

        Every figure it can contain (an age bound, a games minimum) is a filter
        recorded in the facts, so the FactValidator can back it.
        """
        bits: List[str] = []
        if query.get("team"):
            bits.append(next((t["name"] for t in facets.get("teams", [])
                              if t["external_id"] == query["team"]), query["team"]))
        for key in ("position", "nationality"):
            if query.get(key):
                bits.append(str(query[key]))
        lo, hi = query.get("min_age"), query.get("max_age")
        if lo and hi:
            bits.append(f"de {lo} a {hi} años")
        elif lo:
            bits.append(f"{lo} años o más")
        elif hi:
            bits.append(f"{hi} años o menos")
        if query.get("min_games"):
            bits.append(f"mínimo {query['min_games']} partidos")
        return " · ".join(bits).upper()

    def _custom_context(
        self, row: Dict[str, Any], metric: str, per_game: bool = False,
    ) -> str:
        """The supporting line under the name. It never repeats the ranked
        figure — that one is already the big number on the right — and when the
        ranking is per-game the supporting stats are per-game too, so the line
        matches the number the card is claiming."""
        g = row.get("games_played") or 0
        def _v(key: str) -> str:
            raw = row.get(key) or 0
            if per_game and g and key != "games_played":
                return self._es_number(round(raw / g, 1))
            return str(raw)
        parts = [(f"{g} PJ", "games_played"),
                 (f"{_v('points')} PTS", "points"),
                 (f"{_v('rebounds')} REB", "rebounds"),
                 (f"{_v('assists')} AST", "assists")]
        return " · ".join(text for text, key in parts if key != metric)

    # ------------------------------------------------------------- imagery
    def list_image_catalog(self, season_code: str) -> Dict[str, Any]:
        from ..domain.value_objects import SeasonCode
        from .rendering.feb_image_assets import PLAYER_PHOTO_URL, TEAM_CREST_URL

        season = SeasonCode(season_code)
        overrides = self._image_override_repo.list_meta()

        player_ids = [
            a.player_external_id
            for a in self._stats_repo.list_season_player_aggregates(season)
        ]
        team_ids = [
            a.team_external_id
            for a in self._stats_repo.list_season_team_aggregates(season)
        ]
        player_names = self._player_repo.get_many_by_external_ids(set(player_ids))
        team_names = self._team_repo.get_many_by_external_ids(set(team_ids))

        def _name(catalog, pid):
            rec = catalog.get(pid)
            return rec.name if rec is not None else None

        # Each player's team, in ONE query — the gallery filters by team, and
        # asking per player would be ~450 round trips on a page load.
        player_team = self._stats_repo.list_season_player_teams(season)

        def _entry(kind, pid, url_tmpl, name, team_id=None):
            meta = overrides.get((kind, pid))
            entry = {
                "kind": kind,
                "external_id": pid,
                "name": name or pid,
                "feb_url": url_tmpl.format(**{f"{kind}_external_id": pid})
                if kind == "player"
                else url_tmpl.format(team_external_id=pid),
                "has_override": meta is not None,
                "override_updated_at": meta.updated_at if meta else None,
            }
            if kind == "player":
                entry["team_external_id"] = team_id
                entry["team_name"] = _name(team_names, team_id) if team_id else None
            return entry

        players = sorted(
            (_entry("player", pid, PLAYER_PHOTO_URL, _name(player_names, pid),
                    player_team.get(pid))
             for pid in player_ids),
            key=lambda e: e["name"].lower(),
        )
        teams = sorted(
            (_entry("team", tid, TEAM_CREST_URL, _name(team_names, tid))
             for tid in team_ids),
            key=lambda e: e["name"].lower(),
        )
        return {"season_code": season_code, "players": players, "teams": teams}

    def get_image_override(
        self, kind: str, external_id: str
    ) -> Optional[Dict[str, Any]]:
        ov = self._image_override_repo.get(kind, external_id)
        if ov is None:
            return None
        return {
            "content_type": ov.content_type,
            "image": ov.image,
            "byte_size": ov.byte_size,
            "updated_at": ov.updated_at,
        }

    def put_image_override(
        self, kind: str, external_id: str, image: bytes, content_type: str
    ) -> Dict[str, Any]:
        self._image_override_repo.put(kind, external_id, image, content_type)
        return {
            "kind": kind, "external_id": external_id,
            "content_type": content_type, "byte_size": len(image),
        }

    def delete_image_override(self, kind: str, external_id: str) -> bool:
        return self._image_override_repo.delete(kind, external_id)

    # -------------------------------------------------- media library
    @staticmethod
    def _meta_to_dict(m: Any) -> Dict[str, Any]:
        return {
            "asset_id": m.asset_id, "kind": m.kind, "external_id": m.external_id,
            "role": m.role, "approved": m.approved, "content_type": m.content_type,
            "byte_size": m.byte_size, "source": m.source, "source_url": m.source_url,
            "photographer": m.photographer, "copyright": m.copyright,
            "license_type": m.license_type, "commercial_use": m.commercial_use,
            "date_acquired": m.date_acquired, "expiry": m.expiry,
            "tags": m.tags, "notes": m.notes,
            "created_at": m.created_at, "updated_at": m.updated_at,
        }

    def list_media_assets(self, kind: str, external_id: str) -> List[Dict[str, Any]]:
        return [self._meta_to_dict(m)
                for m in self._media_asset_repo.list_meta(kind, external_id)]

    def get_media_image(self, asset_id: str) -> Optional[Dict[str, Any]]:
        img = self._media_asset_repo.get_image(asset_id)
        if img is None:
            return None
        return {"content_type": img.content_type, "image": img.image}

    def add_media_asset(
        self, kind: str, external_id: str, image: bytes, content_type: str, *,
        approved: bool = False, source: Optional[str] = None,
        source_url: Optional[str] = None, photographer: Optional[str] = None,
        license_type: Optional[str] = None, commercial_use: bool = False,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        # New photos land as 'alternate' — the operator promotes explicitly, so
        # the entity's primary never changes just because someone uploaded.
        # Exception: the entity has NO photos yet, in which case the first one
        # is the primary by default (otherwise the entity would sit with photos
        # but nothing selected).
        existing = self._media_asset_repo.list_meta(kind, external_id)
        role = "primary" if not existing else "alternate"
        aid = self._media_asset_repo.add(
            kind, external_id, image, content_type,
            role=role, approved=approved,
            source=source, source_url=source_url, photographer=photographer,
            license_type=license_type, commercial_use=commercial_use, notes=notes,
        )
        meta = self._media_asset_repo.get_meta(aid)
        return self._meta_to_dict(meta) if meta is not None else {"asset_id": aid}

    def promote_media_primary(self, asset_id: str) -> bool:
        return self._media_asset_repo.promote_primary(asset_id)

    def set_media_approved(self, asset_id: str, approved: bool) -> bool:
        return self._media_asset_repo.set_approved(asset_id, approved)

    def delete_media_asset(self, asset_id: str) -> bool:
        return self._media_asset_repo.delete(asset_id)

    def edit_content(
        self,
        content_id: str,
        *,
        section_label: Optional[str] = None,
        caption: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        item = self._pipeline().edit_content(
            content_id, section_label=section_label, caption=caption
        )
        return item.to_dict() if item is not None else None

    def purge_content_queue(self) -> Dict[str, Any]:
        """Housekeeping: drop rejected/failed cards. Live and published items
        are never touched (the queue enforces that)."""
        removed = self._pipeline().queue.purge()
        return {"removed": removed}

    def delete_content_item(self, content_id: str) -> bool:
        """Discard one item outright — the operator asked for it (from Ideas
        preview or the Cola row). Unconditional at any status; the queue is
        the operator's tool, not a sacred ledger. Also drops the item from
        the ephemeral preview store so Descartar covers both worlds."""
        preview_dropped = self._preview_store.pop(content_id) is not None
        queue = self._pipeline().queue
        queue_dropped = False
        if hasattr(queue, "delete"):
            queue_dropped = queue.delete(content_id)
        return preview_dropped or queue_dropped

    def commit_preview(self, content_id: str) -> Optional[Dict[str, Any]]:
        """Promote a previewed card from the ephemeral store into the real
        queue as PENDING_REVIEW. Returns the queued item, or None when the
        preview id is unknown / already expired."""
        item = self._preview_store.pop(content_id)
        if item is None:
            return None
        self._pipeline().queue.add(item)
        return item.to_dict()

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
        from .persistence.image_override_repo import SqliteImageOverrideRepository
        from .persistence.media_asset_repo import SqliteMediaAssetRepository

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
            "image_override": SqliteImageOverrideRepository(self.db),
            "media_asset": SqliteMediaAssetRepository(self.db),
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
        from .persistence.image_override_repo import PgImageOverrideRepository
        from .persistence.media_asset_repo import PgMediaAssetRepository

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
            "image_override": PgImageOverrideRepository(self.db),
            "media_asset": PgMediaAssetRepository(self.db),
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