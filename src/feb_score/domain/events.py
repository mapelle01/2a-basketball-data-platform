from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional

from .value_objects import Actor, EventMeta, ExternalId, MatchId, PlayerId, PublicationId, SnapshotId, TeamId


@dataclass(frozen=True)
class DomainEvent:
    event_id: str
    meta: EventMeta
    source: Dict[str, Any]
    payload: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MatchUpserted(DomainEvent):
    pass


@dataclass(frozen=True)
class MatchValidationStarted(DomainEvent):
    pass


@dataclass(frozen=True)
class MatchValidated(DomainEvent):
    pass


@dataclass(frozen=True)
class MatchFinalized(DomainEvent):
    pass


@dataclass(frozen=True)
class ValidationFailed(DomainEvent):
    pass


@dataclass(frozen=True)
class CorrectionProposed(DomainEvent):
    pass


@dataclass(frozen=True)
class CorrectionApproved(DomainEvent):
    pass


@dataclass(frozen=True)
class MatchUpdatedByCorrection(DomainEvent):
    pass


@dataclass(frozen=True)
class CorrectionRejected(DomainEvent):
    pass


@dataclass(frozen=True)
class PlayerRegistered(DomainEvent):
    pass


@dataclass(frozen=True)
class StandingSnapshotGenerated(DomainEvent):
    pass


@dataclass(frozen=True)
class LeaderboardGenerated(DomainEvent):
    pass


@dataclass(frozen=True)
class PlayerRatingComputed(DomainEvent):
    pass


@dataclass(frozen=True)
class PlayerMilestoneReached(DomainEvent):
    pass


@dataclass(frozen=True)
class PublicationCreated(DomainEvent):
    pass


@dataclass(frozen=True)
class SeasonBackfillStarted(DomainEvent):
    pass


@dataclass(frozen=True)
class SeasonBackfillCompleted(DomainEvent):
    pass


@dataclass(frozen=True)
class DomainAlert(DomainEvent):
    pass


@dataclass(frozen=True)
class ContentGenerated(DomainEvent):
    pass
