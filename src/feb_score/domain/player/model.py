from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional

from ..common import AggregateRoot
from ..errors import InvalidPlayerRegistration
from ..value_objects import ExternalId, PlayerId, SeasonCode


@dataclass(frozen=True)
class PlayerRegistration:
    team_external_id: str
    season_code: SeasonCode
    registration_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    dorsal: Optional[int] = None
    registered_at: Optional[date] = None
    registered_to: Optional[date] = None
    role: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.team_external_id or len(self.team_external_id.strip()) == 0:
            raise ValueError("team_external_id must be a non-empty string")
        if self.dorsal is not None and self.dorsal < 0:
            raise ValueError("dorsal must be non-negative")


@dataclass
class Player(AggregateRoot):
    external_id: ExternalId
    player_id: PlayerId
    name: str
    birth_date: Optional[date] = None
    nationality: Optional[str] = None
    position: Optional[str] = None
    registrations: List[PlayerRegistration] = field(default_factory=list)

    def register_for_team(
        self,
        team_external_id: str,
        season_code: SeasonCode,
        dorsal: Optional[int] = None,
        registered_at: Optional[date] = None,
        registered_to: Optional[date] = None,
        role: Optional[str] = None,
        registration_id: Optional[str] = None,
    ) -> PlayerRegistration:
        self.ensure_can_register_for_team(
            team_external_id=team_external_id,
            season_code=season_code,
            dorsal=dorsal,
        )

        registration = PlayerRegistration(
            team_external_id=team_external_id,
            season_code=season_code,
            registration_id=registration_id or str(uuid.uuid4()),
            dorsal=dorsal,
            registered_at=registered_at,
            registered_to=registered_to,
            role=role,
        )
        self.registrations.append(registration)
        return registration

    def ensure_can_register_for_team(
        self,
        team_external_id: str,
        season_code: SeasonCode,
        dorsal: Optional[int] = None,
    ) -> None:
        if any(
            reg.team_external_id == team_external_id and reg.season_code == season_code
            for reg in self.registrations
        ):
            raise InvalidPlayerRegistration("Player is already registered for this team and season")

        PlayerRegistration(
            team_external_id=team_external_id,
            season_code=season_code,
            dorsal=dorsal,
        )

    def is_registered_for(self, team_external_id: str, season_code: SeasonCode) -> bool:
        return any(
            reg.team_external_id == team_external_id and reg.season_code == season_code
            for reg in self.registrations
        )

    def get_registration(self, registration_id: str) -> Optional[PlayerRegistration]:
        return next(
            (reg for reg in self.registrations if reg.registration_id == registration_id),
            None,
        )
