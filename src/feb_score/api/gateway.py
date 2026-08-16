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
    def readiness(self) -> Readiness:
        """Non-destructive dependency check (database reachable + schema version)."""
        raise NotImplementedError