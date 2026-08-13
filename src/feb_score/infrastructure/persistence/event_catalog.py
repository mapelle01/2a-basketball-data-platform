"""Shared domain-event catalog: mapping event class name -> class, aggregate
reference derivation and reconstruction. Backend-agnostic: both the SQLite and
PostgreSQL event stores build on this module so a row from either store can be
reconstructed into a ``DomainEvent``."""

from __future__ import annotations

import json
from typing import Any, Dict

from ...domain.events import (
    CorrectionApproved,
    CorrectionProposed,
    CorrectionRejected,
    DomainEvent,
    LeaderboardGenerated,
    MatchFinalized,
    MatchUpdatedByCorrection,
    MatchUpserted,
    MatchValidated,
    MatchValidationStarted,
    PlayerMilestoneReached,
    PlayerRatingComputed,
    PlayerRegistered,
    PublicationCreated,
    SeasonBackfillCompleted,
    SeasonBackfillStarted,
    StandingSnapshotGenerated,
    ValidationFailed,
)

EVENT_TYPES: Dict[str, type] = {
    event_cls.__name__: event_cls
    for event_cls in (
        MatchUpserted,
        MatchValidationStarted,
        MatchValidated,
        MatchFinalized,
        ValidationFailed,
        CorrectionProposed,
        CorrectionApproved,
        MatchUpdatedByCorrection,
        CorrectionRejected,
        PlayerRegistered,
        StandingSnapshotGenerated,
        LeaderboardGenerated,
        PlayerRatingComputed,
        PlayerMilestoneReached,
        PublicationCreated,
        SeasonBackfillStarted,
        SeasonBackfillCompleted,
    )
}


def aggregate_ref(event: DomainEvent) -> tuple:
    payload = event.payload
    kind = type(event).__name__
    if kind.startswith("Match"):
        return "Match", str(payload.get("external_id") or payload.get("match_external_id") or payload.get("match_uuid") or "")
    if kind.startswith("Correction"):
        return "CorrectionProposal", str(payload.get("proposal_id") or "")
    if kind == "PlayerRegistered":
        return "Player", str(payload.get("player_external_id") or "")
    if kind == "StandingSnapshotGenerated":
        return "StandingSnapshot", str(payload.get("snapshot_id") or "")
    if kind == "LeaderboardGenerated":
        return "Leaderboard", str(payload.get("leaderboard_id") or "")
    if kind == "PlayerRatingComputed" or kind == "PlayerMilestoneReached":
        return "PlayerRating", str(payload.get("player_external_id") or "")
    if kind == "PublicationCreated":
        return "Publication", str(payload.get("publication_id") or "")
    if kind.startswith("SeasonBackfill"):
        return "Season", str(payload.get("season_code") or "")
    return "Unknown", ""


def _json_safe_event(event: DomainEvent) -> dict:
    """Serialize an event to a JSON-safe dict (asdict leaves datetime objects)."""
    return {
        "event_id": event.event_id,
        "meta": {
            "version": event.meta.version,
            "produced_at": event.meta.produced_at.isoformat(),
        },
        "source": event.source,
        "payload": event.payload,
    }


def datetime_from_iso(value: str) -> Any:
    from datetime import datetime

    return datetime.fromisoformat(value)


def reconstruct_event(row) -> DomainEvent:
    """Rebuild a DomainEvent instance from a domain_events row.

    ``row`` must expose ``payload`` (JSON TEXT) and ``event_type`` — both the
    SQLite and the PostgreSQL stores provide exactly that shape.
    """
    payload = json.loads(row["payload"])
    event_type = row["event_type"]
    if event_type not in EVENT_TYPES:
        raise ValueError(f"Unknown event type: {event_type}")
    meta = payload["meta"]
    from ...domain.value_objects import EventMeta

    return EVENT_TYPES[event_type](
        event_id=payload["event_id"],
        meta=EventMeta(version=meta["version"], produced_at=datetime_from_iso(meta["produced_at"])),
        source=payload["source"],
        payload=payload["payload"],
    )