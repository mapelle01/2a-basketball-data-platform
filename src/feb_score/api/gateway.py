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

    @abstractmethod
    def readiness(self) -> Readiness:
        """Non-destructive dependency check (database reachable + schema version)."""
        raise NotImplementedError