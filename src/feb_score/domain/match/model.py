from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from ..common import AggregateRoot
from ..errors import InvalidCorrection, InvalidMatchStateTransition, InvalidScore, MatchAlreadyFinalized, MissingMatchData
from ..events import MatchFinalized, MatchUpdatedByCorrection, MatchUpserted
from ..statistics.model import PlayerStats, TeamStats
from ..value_objects import (
    CompetitionId,
    ExternalId,
    EventMeta,
    MatchId,
    MatchStatus,
    SeasonCode,
    ScoreSummary,
)


@dataclass
class Match(AggregateRoot):
    external_id: ExternalId
    match_id: MatchId
    competition_id: CompetitionId
    season_code: SeasonCode
    round_number: int
    home_team_id: ExternalId
    away_team_id: ExternalId
    scheduled_at: datetime
    status: MatchStatus = field(default_factory=lambda: MatchStatus("SCHEDULED"))
    source: Dict[str, object] = field(default_factory=dict)
    venue: Optional[Dict[str, str]] = None
    raw: Optional[Dict[str, str]] = None
    score_summary: Optional[ScoreSummary] = None
    home_team_stats: Optional[TeamStats] = None
    away_team_stats: Optional[TeamStats] = None
    player_stats: Tuple[PlayerStats, ...] = field(default_factory=tuple)
    version: int = 1
    correction_history: List[Dict[str, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.home_team_id == self.away_team_id:
            raise ValueError("home_team_id and away_team_id must differ")
        if self.round_number < 0:
            raise ValueError("round_number must be non-negative")

    @classmethod
    def create(
        cls,
        external_id: ExternalId,
        match_id: MatchId,
        competition_id: CompetitionId,
        season_code: SeasonCode,
        round_number: int,
        home_team_id: ExternalId,
        away_team_id: ExternalId,
        scheduled_at: datetime,
        source: Dict[str, object],
        venue: Optional[Dict[str, str]] = None,
        raw: Optional[Dict[str, str]] = None,
    ) -> "Match":
        match = cls(
            external_id=external_id,
            match_id=match_id,
            competition_id=competition_id,
            season_code=season_code,
            round_number=round_number,
            home_team_id=home_team_id,
            away_team_id=away_team_id,
            scheduled_at=scheduled_at,
            source=source,
            venue=venue,
            raw=raw,
        )
        match._record_event(
            MatchUpserted(
                event_id=str(uuid.uuid4()),
                meta=EventMeta(version="1.0", produced_at=datetime.utcnow()),
                source={"origin": "system", "actor": {"id": "system"}},
                payload={
                    "external_id": str(match.external_id),
                    "match_uuid": str(match.match_id),
                    "competition_id": str(match.competition_id),
                    "season_code": str(match.season_code),
                    "status": str(match.status),
                    "source": match.source,
                },
            )
        )
        return match

    def upsert(self, **updates: Any) -> None:
        updatable = {
            "competition_id": CompetitionId,
            "season_code": SeasonCode,
            "round_number": int,
            "home_team_id": ExternalId,
            "away_team_id": ExternalId,
            "scheduled_at": datetime,
            "status": MatchStatus,
            "source": dict,
            "venue": dict,
            "raw": dict,
        }

        for field_name, field_type in updatable.items():
            if field_name in updates:
                value = updates[field_name]
                if field_name in {"source", "venue", "raw"}:
                    setattr(self, field_name, value)
                else:
                    # Coerce raw values (e.g. a str for scheduled_at) but tolerate
                    # already-typed values (e.g. a datetime) from callers like the
                    # create/update handler.
                    if not isinstance(value, field_type):
                        value = field_type(value)
                    setattr(self, field_name, value)

        # Every domain mutation bumps the aggregate version so optimistic
        # concurrency (persistence) can detect concurrent writes.
        self.version += 1

        self._record_event(
            MatchUpserted(
                event_id=str(uuid.uuid4()),
                meta=EventMeta(version="1.0", produced_at=datetime.utcnow()),
                source={"origin": "system", "actor": {"id": "system"}},
                payload={
                    "external_id": str(self.external_id),
                    "match_uuid": str(self.match_id),
                    "competition_id": str(self.competition_id),
                    "season_code": str(self.season_code),
                    "status": str(self.status),
                    "source": self.source,
                },
            )
        )

    def start(self, actor_id: str = "system") -> None:
        if self.status != MatchStatus("SCHEDULED"):
            raise InvalidMatchStateTransition(f"Match can only start from SCHEDULED status, not {self.status}")
        self.status = MatchStatus("IN_PLAY")
        self._record_event(
            MatchUpserted(
                event_id=str(uuid.uuid4()),
                meta=EventMeta(version="1.0", produced_at=datetime.utcnow()),
                source={"origin": "system", "actor": {"id": actor_id}},
                payload={
                    "external_id": str(self.external_id),
                    "match_uuid": str(self.match_id),
                    "competition_id": str(self.competition_id),
                    "season_code": str(self.season_code),
                    "status": str(self.status),
                    "source": self.source,
                },
            )
        )

    def postpone(self, actor_id: str = "system") -> None:
        if self.status != MatchStatus("SCHEDULED"):
            raise InvalidMatchStateTransition(f"Match can only be postponed from SCHEDULED status, not {self.status}")
        self.status = MatchStatus("POSTPONED")
        self._record_event(
            MatchUpserted(
                event_id=str(uuid.uuid4()),
                meta=EventMeta(version="1.0", produced_at=datetime.utcnow()),
                source={"origin": "system", "actor": {"id": actor_id}},
                payload={
                    "external_id": str(self.external_id),
                    "match_uuid": str(self.match_id),
                    "competition_id": str(self.competition_id),
                    "season_code": str(self.season_code),
                    "status": str(self.status),
                    "source": self.source,
                },
            )
        )

    def cancel(self, actor_id: str = "system") -> None:
        if self.status not in {MatchStatus("SCHEDULED"), MatchStatus("IN_PLAY")}: 
            raise InvalidMatchStateTransition(f"Match can only be cancelled from SCHEDULED or IN_PLAY status, not {self.status}")
        self.status = MatchStatus("CANCELLED")
        self._record_event(
            MatchUpserted(
                event_id=str(uuid.uuid4()),
                meta=EventMeta(version="1.0", produced_at=datetime.utcnow()),
                source={"origin": "system", "actor": {"id": actor_id}},
                payload={
                    "external_id": str(self.external_id),
                    "match_uuid": str(self.match_id),
                    "competition_id": str(self.competition_id),
                    "season_code": str(self.season_code),
                    "status": str(self.status),
                    "source": self.source,
                },
            )
        )

    def finalize(
        self,
        score_summary: Optional[ScoreSummary] = None,
        home_team_stats: Optional[TeamStats] = None,
        away_team_stats: Optional[TeamStats] = None,
        player_stats: Optional[Tuple[PlayerStats, ...]] = None,
        finalized_at: datetime = None,
        actor_id: str = "system",
        strict: bool = False,
    ) -> None:
        if self.status == MatchStatus("FINALIZED"):
            raise MatchAlreadyFinalized("Match is already finalized")
        if self.status not in {MatchStatus("SCHEDULED"), MatchStatus("IN_PLAY")}:
            raise InvalidMatchStateTransition(f"Cannot finalize match from status {self.status}")

        if score_summary is not None:
            self.score_summary = score_summary
        if home_team_stats is not None:
            self.home_team_stats = home_team_stats
        if away_team_stats is not None:
            self.away_team_stats = away_team_stats
        if player_stats is not None:
            self.player_stats = player_stats
        self.validate_finalization(strict=strict)
        self.status = MatchStatus("FINALIZED")
        self.version += 1
        if finalized_at is None:
            finalized_at = datetime.utcnow()

        self._record_event(
            MatchFinalized(
                event_id=str(uuid.uuid4()),
                meta=EventMeta(version="1.0", produced_at=datetime.utcnow()),
                source={"origin": "admin", "actor": {"id": actor_id}},
                payload={
                    "external_id": str(self.external_id),
                    "match_uuid": str(self.match_id),
                    "finalized_at": finalized_at.isoformat(),
                    "score_summary": {
                        "home_score": self.score_summary.home_score,
                        "away_score": self.score_summary.away_score,
                        "periods": [
                            {"period": p.period, "home": p.home, "away": p.away}
                            for p in self.score_summary.periods
                        ],
                    },
                },
            )
        )

    def apply_correction(
        self,
        correction_id: str,
        changes: list[Dict[str, Any]],
        approved_at: datetime,
        approver_id: str,
        reason: str,
    ) -> None:
        if self.status != MatchStatus("FINALIZED"):
            raise InvalidCorrection("Correction can only be applied to finalized matches")

        previous_version = self.version

        new_score_summary = self.score_summary
        new_player_stats = list(self.player_stats)

        for change in changes:
            op = change.get("op")
            if op == "update_score":
                home_score = change.get("home_score")
                away_score = change.get("away_score")
                if home_score is None or away_score is None:
                    raise InvalidCorrection("update_score requires home_score and away_score")
                
                existing_periods = new_score_summary.periods if new_score_summary else tuple()
                
                if existing_periods:
                    if sum(p.home for p in existing_periods) != home_score or sum(p.away for p in existing_periods) != away_score:
                        raise InvalidCorrection("Provided scores do not match the sum of existing period scores")
                
                new_score_summary = ScoreSummary(
                    home_score=home_score,
                    away_score=away_score,
                    periods=existing_periods,
                )
            elif op == "update_player_stat":
                player_external_id = change.get("player_external_id")
                if player_external_id is None:
                    raise InvalidCorrection("update_player_stat requires player_external_id")
                updated = False
                for index, stat in enumerate(new_player_stats):
                    if stat.player_external_id == player_external_id:
                        updated_values = {**stat.to_dict(), **change.get("values", {})}
                        new_player_stats[index] = PlayerStats(**updated_values)
                        updated = True
                if not updated:
                    raise InvalidCorrection("Player stat update refers to unknown player")
            elif op in {"add_event", "remove_event", "update_event"}:
                raise InvalidCorrection(f"Unsupported correction operation: {op}")
            else:
                raise InvalidCorrection(f"Unsupported correction operation: {op}")

        self.score_summary = new_score_summary
        self.player_stats = tuple(new_player_stats)

        self.version += 1
        self.correction_history.append(
            {
                "correction_id": correction_id,
                "approved_at": approved_at.isoformat(),
                "approver_id": approver_id,
                "reason": reason,
                "previous_version": str(previous_version),
                "new_version": str(self.version),
            }
        )

        self._record_event(
            MatchUpdatedByCorrection(
                event_id=str(uuid.uuid4()),
                meta=EventMeta(version="1.0", produced_at=datetime.utcnow()),
                source={"origin": "admin", "actor": {"id": approver_id}},
                payload={
                    "match_external_id": str(self.external_id),
                    "match_uuid": str(self.match_id),
                    "previous_version": str(previous_version),
                    "new_version": str(self.version),
                    "applied_at": approved_at.isoformat(),
                    "summary": {"reason": reason, "changes": changes},
                },
            )
        )

    def validate_finalization(self, strict: bool = False) -> None:
        # TODO: Implement strict validation semantics (e.g. comparing player stats vs team stats)
        # Currently strict mode has no additional rules implemented in the domain.
        if self.score_summary is None:
            raise MissingMatchData("Finalized match requires score summary")
        if self.home_team_stats is None or self.away_team_stats is None:
            raise MissingMatchData("Finalized match requires team stats")

        if self.score_summary.home_score < 0 or self.score_summary.away_score < 0:
            raise InvalidScore("Scores must be non-negative")

        if self.score_summary.total_points == 0:
            raise InvalidScore("Finalized match must have a result")
