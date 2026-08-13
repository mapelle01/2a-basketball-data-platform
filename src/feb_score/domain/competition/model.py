from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..common import AggregateRoot
from ..value_objects import CompetitionId, ExternalId, SeasonCode


@dataclass(frozen=True)
class RoundDefinition:
    number: int
    label: str

    def __post_init__(self) -> None:
        if self.number < 1:
            raise ValueError("round number must be positive")
        if not self.label:
            raise ValueError("round label must be provided")


@dataclass
class Season:
    season_code: SeasonCode
    rules_version: str
    rounds: List[RoundDefinition] = field(default_factory=list)

    def add_round(self, round_definition: RoundDefinition) -> None:
        if any(r.number == round_definition.number for r in self.rounds):
            raise ValueError("Round number already exists for this season")
        self.rounds.append(round_definition)


@dataclass
class Competition(AggregateRoot):
    external_id: ExternalId
    competition_id: CompetitionId
    name: str
    seasons: Dict[str, Season] = field(default_factory=dict)

    def define_season(self, season_code: SeasonCode, rules_version: str) -> Season:
        if str(season_code) in self.seasons:
            raise ValueError("Season already exists")
        season = Season(season_code=season_code, rules_version=rules_version)
        self.seasons[str(season_code)] = season
        return season

    def get_season(self, season_code: SeasonCode) -> Optional[Season]:
        return self.seasons.get(str(season_code))
