"""HTTP API boundary (FASE 11).

The ``CommandGateway`` is the ONLY surface the HTTP layer touches. It abstracts
the CommandRunner + Application handlers + repository wiring behind a narrow,
SQLite-free, aggregate-free contract.

The API package imports NOTHING from concrete persistence (no repositories, no
SQLite, no aggregates): errors raised through the gateway use the shared error
taxonomy (``ContractValidationError``, ``DomainError``, ``StaleVersionError``,
``InfrastructureError``) so the HTTP layer can map them without knowing the
implementation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class ImageRenderingUnavailable(Exception):
    """This deployment cannot rasterise cards (no rasteriser installed).

    Defined on the PORT, not in the rendering module: the HTTP layer has to map
    the failure to a status code, and it may not import concrete infrastructure
    to do so. The adapter translates its own error into this one.
    """


class ImageRenderingFailed(Exception):
    """The rasteriser ran and refused the card."""


@dataclass(frozen=True)
class EventRef:
    """Lightweight, stable reference to a produced event (never the full event)."""

    event_id: str
    event_type: str


@dataclass(frozen=True)
class CommandResult:
    """The command was accepted and executed. Events are references only; their
    persistence/dispatch is the Application's responsibility (outbox semantics)."""

    command_id: str
    events: List[EventRef] = field(default_factory=list)


@dataclass(frozen=True)
class Readiness:
    ready: bool
    checks: Dict[str, str] = field(default_factory=dict)


class CommandGateway(ABC):
    @abstractmethod
    def run(
        self,
        command_type: str,
        *,
        command_id: str,
        actor: Dict[str, Any],
        payload: Dict[str, Any],
    ) -> CommandResult:
        """Execute a command. Raises (contract/domain/infrastructure) on failure."""
        raise NotImplementedError

    # Read side: minimal projections for verification (no business logic).
    @abstractmethod
    def get_match(self, external_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_player(self, external_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_team(self, external_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_competition(self, external_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_leaderboard(self, leaderboard_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_correction_proposal(self, proposal_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    # FASE 23.5 — season analytics reads (list DTOs, empty list when no data).
    # Metric validation raises ValueError (mapped to 400 by the HTTP layer).
    @abstractmethod
    def list_season_player_aggregates(
        self, season_code: str, limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def list_season_team_aggregates(
        self, season_code: str, limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def list_season_player_leaderboard(
        self, season_code: str, metric: str, limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def list_season_team_leaderboard(
        self, season_code: str, metric: str, limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def list_season_player_metrics(
        self, season_code: str, limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def list_season_team_metrics(
        self, season_code: str, limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError

    # ------------------------------------------------------------ FASE 24
    # Match & player exploration reads (HTTP -> gateway -> ExplorationService).
    # A None result means the referenced entity does not exist (HTTP 404);
    # season filters never 404 on their own (they are filters, not resources).
    @abstractmethod
    def get_match_detail(self, external_id: str) -> Optional[Dict[str, Any]]:
        """A match plus its boxscore projection (team/player stats)."""
        raise NotImplementedError

    @abstractmethod
    def get_player_profile(
        self, season_code: str, player_external_id: str
    ) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_team_profile(
        self, season_code: str, team_external_id: str
    ) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def search_players(self, q: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def search_teams(self, q: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
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
        raise NotImplementedError

    @abstractmethod
    def list_power_ranking(
        self, season_code: str, limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_player_form_index(
        self, season_code: str, player_external_id: str, window: int = 5
    ) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_team_form_index(
        self, season_code: str, team_external_id: str, window: int = 5
    ) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def system_status(self) -> Dict[str, Any]:
        """Operational metrics: entity counts, data freshness, pending events."""
        raise NotImplementedError

    @abstractmethod
    def readiness(self) -> Readiness:
        """Non-destructive dependency check (database reachable + schema version)."""
        raise NotImplementedError

    @abstractmethod
    def generate_match_result_content(
        self, match_external_id: str
    ) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    # ------------------------------------------------ Content Engine pipeline
    @abstractmethod
    def run_content_pipeline(
        self, season_code: str, round_number: int, top_n: int = 5
    ) -> Dict[str, Any]:
        """Run the Content Engine over a finalized round; returns a summary of
        the queued content items (no rendered SVG in the summary)."""
        raise NotImplementedError

    @abstractmethod
    def list_content_queue(
        self, status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_content_item(self, content_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def render_content_item(self, content_id: str) -> Optional[str]:
        """Return the rendered SVG string for a content item, or None if unknown."""
        raise NotImplementedError

    @abstractmethod
    def render_content_item_png(
        self, content_id: str, width: int, height: int
    ) -> Optional[bytes]:
        """The publishable image: the card rasterised at post size, or None if
        the item is unknown. Raises ImageRenderingUnavailable when this
        deployment has no rasteriser, ImageRenderingFailed when it refuses."""
        raise NotImplementedError

    @abstractmethod
    def edit_content(
        self,
        content_id: str,
        *,
        section_label: Optional[str] = None,
        caption: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Hand-edit a card's on-image title and/or Instagram caption. Returns
        the updated item, or None if unknown. Raises when the card is not in an
        editable state."""
        raise NotImplementedError

    # ----------------------------------------------- content lifecycle actions
    # Each returns the updated item dict, or None if the content_id is unknown.
    # Illegal transitions raise a DomainError the HTTP layer maps to 409.
    @abstractmethod
    def approve_content(self, content_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def reject_content(self, content_id: str, reason: Optional[str] = None) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def schedule_content(self, content_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def publish_content(self, content_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError