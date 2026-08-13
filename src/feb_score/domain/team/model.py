from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import List, Optional

from ..common import AggregateRoot
from ..errors import InvalidPlayerRegistration
from ..value_objects import ExternalId, TeamId, SeasonCode


@dataclass(frozen=True)
class TeamPlayerRegistration:
    player_external_id: str
    season_code: SeasonCode
    registration_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    dorsal: Optional[int] = None

    def __post_init__(self) -> None:
        if not self.player_external_id or len(self.player_external_id.strip()) == 0:
            raise ValueError("player_external_id must be a non-empty string")
        if self.dorsal is not None and self.dorsal < 0:
            raise ValueError("dorsal must be non-negative")


@dataclass
class Team(AggregateRoot):
    external_id: ExternalId
    team_id: TeamId
    name: str
    registrations: List[TeamPlayerRegistration] = field(default_factory=list)

    def add_player_registration(
        self,
        player_external_id: str,
        season_code: SeasonCode,
        dorsal: Optional[int] = None,
        registration_id: Optional[str] = None,
    ) -> TeamPlayerRegistration:
        self.ensure_can_add_player_registration(
            player_external_id=player_external_id,
            season_code=season_code,
            dorsal=dorsal,
        )

        registration = TeamPlayerRegistration(
            player_external_id=player_external_id,
            season_code=season_code,
            registration_id=registration_id or str(uuid.uuid4()),
            dorsal=dorsal,
        )
        self.registrations.append(registration)
        return registration

    def ensure_can_add_player_registration(
        self,
        player_external_id: str,
        season_code: SeasonCode,
        dorsal: Optional[int] = None,
    ) -> None:
        if any(
            reg.player_external_id == player_external_id and reg.season_code == season_code
            for reg in self.registrations
        ):
            raise InvalidPlayerRegistration("Player is already registered in the team for this season")

        TeamPlayerRegistration(
            player_external_id=player_external_id,
            season_code=season_code,
            dorsal=dorsal,
        )

    def has_player(self, player_external_id: str, season_code: SeasonCode) -> bool:
        return any(
            reg.player_external_id == player_external_id and reg.season_code == season_code
            for reg in self.registrations
        )
