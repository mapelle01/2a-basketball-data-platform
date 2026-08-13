from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

UUID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


@dataclass(frozen=True)
class MatchId:
    value: str

    def __post_init__(self) -> None:
        if not UUID_PATTERN.match(self.value):
            raise ValueError("match_id must be a valid UUID string")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class PlayerId:
    value: str

    def __post_init__(self) -> None:
        if not UUID_PATTERN.match(self.value):
            raise ValueError("player_id must be a valid UUID string")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class TeamId:
    value: str

    def __post_init__(self) -> None:
        if not UUID_PATTERN.match(self.value):
            raise ValueError("team_id must be a valid UUID string")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class CompetitionId:
    value: str

    def __post_init__(self) -> None:
        if not self.value or len(self.value.strip()) == 0:
            raise ValueError("competition_id must be a non-empty string")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class SeasonCode:
    value: str

    def __post_init__(self) -> None:
        if not re.match(r"^[0-9]{4}-[0-9]{2,4}$", self.value):
            raise ValueError("season_code must follow YYYY-YY or YYYY-YYYY format")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class ExternalId:
    value: str

    def __post_init__(self) -> None:
        if not self.value or len(self.value.strip()) == 0:
            raise ValueError("external_id must be a non-empty string")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class SnapshotId:
    value: str

    def __post_init__(self) -> None:
        if not UUID_PATTERN.match(self.value):
            raise ValueError("snapshot_id must be a valid UUID string")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class PublicationId:
    value: str

    def __post_init__(self) -> None:
        if not UUID_PATTERN.match(self.value):
            raise ValueError("publication_id must be a valid UUID string")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class CorrectionProposalId:
    value: str

    def __post_init__(self) -> None:
        if not UUID_PATTERN.match(self.value):
            raise ValueError("correction_proposal_id must be a valid UUID string")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class LeaderboardId:
    value: str

    def __post_init__(self) -> None:
        if not UUID_PATTERN.match(self.value):
            raise ValueError("leaderboard_id must be a valid UUID string")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class RatingValue:
    value: float

    def __post_init__(self) -> None:
        if self.value < 0:
            raise ValueError("rating_value must be non-negative")

    def __str__(self) -> str:
        return f"{self.value:.2f}"


@dataclass(frozen=True)
class RatingVersion:
    value: str

    def __post_init__(self) -> None:
        if not self.value or len(self.value.strip()) == 0:
            raise ValueError("rating_version must be a non-empty string")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class PeriodScore:
    period: int
    home: int
    away: int

    def __post_init__(self) -> None:
        if self.period < 1:
            raise ValueError("period must be positive")
        if self.home < 0 or self.away < 0:
            raise ValueError("period scores must be non-negative")


@dataclass(frozen=True)
class ScoreSummary:
    home_score: int
    away_score: int
    periods: tuple[PeriodScore, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.home_score < 0 or self.away_score < 0:
            raise ValueError("final scores must be non-negative")
        if self.periods:
            if sum(p.home for p in self.periods) != self.home_score:
                raise ValueError("sum of home period scores must equal final home_score")
            if sum(p.away for p in self.periods) != self.away_score:
                raise ValueError("sum of away period scores must equal final away_score")

    @property
    def total_points(self) -> int:
        return self.home_score + self.away_score


@dataclass(frozen=True)
class MatchStatus:
    value: str

    VALID_STATUSES = {"PROVISIONAL", "SCHEDULED", "IN_PLAY", "FINALIZED", "POSTPONED", "CANCELLED"}

    def __post_init__(self) -> None:
        if self.value not in self.VALID_STATUSES:
            raise ValueError(f"Invalid match status: {self.value}")

    def __str__(self) -> str:
        return self.value


VALID_ACTOR_ROLES = ("editor", "admin", "system")

# Single source of truth for the role hierarchy: "system" is the machine /
# internal principal (fullest access), "admin" manages, "editor" edits.
ROLE_LEVELS = {"editor": 1, "admin": 2, "system": 3}


def role_meets(role: str, minimum: str) -> bool:
    """True when ``role`` is a valid role at or above ``minimum`` (system >= admin >= editor)."""
    return ROLE_LEVELS.get(role, 0) >= ROLE_LEVELS.get(minimum, 0)


@dataclass(frozen=True)
class Actor:
    id: str
    role: str

    def __post_init__(self) -> None:
        if self.role not in VALID_ACTOR_ROLES:
            raise ValueError("actor role must be admin, editor or system")
        if not self.id or len(self.id.strip()) == 0:
            raise ValueError("actor id must be a non-empty string")


@dataclass(frozen=True)
class CommandMeta:
    version: str
    issued_at: datetime

    def __post_init__(self) -> None:
        if self.version != "1.0":
            raise ValueError("command meta version must be 1.0")


@dataclass(frozen=True)
class EventMeta:
    version: str
    produced_at: datetime

    def __post_init__(self) -> None:
        if self.version != "1.0":
            raise ValueError("event meta version must be 1.0")


@dataclass(frozen=True)
class Source:
    origin: str
    actor: Actor

    def __post_init__(self) -> None:
        if self.origin not in {"collector", "admin", "system"}:
            raise ValueError("source origin must be collector, admin or system")
