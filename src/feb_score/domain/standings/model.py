from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Iterable, List, Optional

from ..common import AggregateRoot
from ..errors import InvalidStandingSnapshot
from ..value_objects import CompetitionId, SeasonCode, SnapshotId
from ..match.model import Match


@dataclass(frozen=True)
class StandingEntry:
    team_external_id: str
    played: int
    wins: int
    losses: int
    points_for: int
    points_against: int
    points_difference: int
    points: int


@dataclass
class StandingSnapshot(AggregateRoot):
    snapshot_id: SnapshotId
    competition_id: CompetitionId
    season_code: SeasonCode
    generated_at: datetime
    rounds_included: int
    matches_count: int
    rules_version: str
    description: Optional[str] = None
    entries: List[StandingEntry] = field(default_factory=list)

    @classmethod
    def from_matches(
        cls,
        competition_id: CompetitionId,
        season_code: SeasonCode,
        matches: Iterable[Match],
        rules_version: str,
        generated_at: datetime,
        description: Optional[str] = None,
    ) -> StandingSnapshot:
        standings: Dict[str, Dict[str, int]] = {}
        match_count = 0

        for match in matches:
            if match.status.value != "FINALIZED" or str(match.season_code) != str(season_code):
                continue
            if match.score_summary is None:
                continue
            home = str(match.home_team_id)
            away = str(match.away_team_id)
            home_points = match.score_summary.home_score
            away_points = match.score_summary.away_score
            standings.setdefault(home, {"played": 0, "wins": 0, "losses": 0, "points_for": 0, "points_against": 0, "points": 0})
            standings.setdefault(away, {"played": 0, "wins": 0, "losses": 0, "points_for": 0, "points_against": 0, "points": 0})

            standings[home]["played"] += 1
            standings[away]["played"] += 1
            standings[home]["points_for"] += home_points
            standings[home]["points_against"] += away_points
            standings[away]["points_for"] += away_points
            standings[away]["points_against"] += home_points

            if home_points > away_points:
                standings[home]["wins"] += 1
                standings[away]["losses"] += 1
                standings[home]["points"] += 2
            else:
                standings[away]["wins"] += 1
                standings[home]["losses"] += 1
                standings[away]["points"] += 2

            match_count += 1

        entries: List[StandingEntry] = []
        for team_id, stats in standings.items():
            entries.append(
                StandingEntry(
                    team_external_id=team_id,
                    played=stats["played"],
                    wins=stats["wins"],
                    losses=stats["losses"],
                    points_for=stats["points_for"],
                    points_against=stats["points_against"],
                    points_difference=stats["points_for"] - stats["points_against"],
                    points=stats["points"],
                )
            )

        entries.sort(key=lambda entry: (-entry.points, -entry.points_difference, -entry.points_for, entry.team_external_id))

        if match_count == 0:
            raise InvalidStandingSnapshot("No finalized matches available to build standing snapshot")

        snapshot = StandingSnapshot(
            snapshot_id=SnapshotId(str(uuid.uuid4())),
            competition_id=competition_id,
            season_code=season_code,
            generated_at=generated_at,
            rounds_included=0,
            matches_count=match_count,
            rules_version=rules_version,
            description=description,
            entries=entries,
        )
        return snapshot
