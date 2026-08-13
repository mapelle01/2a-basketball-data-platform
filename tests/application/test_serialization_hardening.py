"""FASE 10 — Serialization hardening.

The JSON blob is the source of truth at rest, so the contract must survive:
empty collections, optional/None fields, unknown (forward) keys, and older
payloads missing optional keys (backward compatibility).
"""

from datetime import datetime
from uuid import uuid4

from feb_score.application.persistence.serialization import (
    match_from_dict,
    match_to_dict,
    player_from_dict,
    player_to_dict,
)
from feb_score.domain.match.model import Match
from feb_score.domain.player.model import Player
from feb_score.domain.value_objects import (
    CompetitionId,
    ExternalId,
    MatchId,
    PlayerId,
    SeasonCode,
)


def _make_match():
    return Match(
        external_id=ExternalId("2513600"),
        match_id=MatchId(str(uuid4())),
        competition_id=CompetitionId("feb-comp"),
        season_code=SeasonCode("2025-2026"),
        round_number=5,
        home_team_id=ExternalId("team-home"),
        away_team_id=ExternalId("team-away"),
        scheduled_at=datetime(2026, 2, 1, 18, 30),
    )


def test_empty_collections_and_optional_fields_round_trip():
    match = _make_match()
    assert match.player_stats == ()
    assert match.correction_history == []
    assert match.source == {}
    assert match.raw is None

    restored = match_from_dict(match_to_dict(match))
    assert restored.player_stats == ()
    assert restored.correction_history == []
    assert restored.raw is None
    assert restored.external_id.value == "2513600"


def test_unknown_extra_keys_are_ignored_on_load():
    data = match_to_dict(_make_match())
    data["future_field"] = {"something": 1}
    restored = match_from_dict(data)
    assert restored.external_id.value == "2513600"


def test_older_payload_missing_optional_keys_still_deserializes():
    """Backward compatibility: data written by an older version (no optional keys)
    must still load with today's reader."""
    data = match_to_dict(_make_match())
    for key in ("venue", "raw", "score_summary", "home_team_stats", "away_team_stats",
                "player_stats", "correction_history"):
        data.pop(key, None)
    restored = match_from_dict(data)
    assert restored.venue is None
    assert restored.raw is None
    assert restored.score_summary is None
    assert restored.player_stats == ()
    assert restored.correction_history == []


def test_player_empty_registrations_round_trip():
    player = Player(
        external_id=ExternalId("pl-1"),
        player_id=PlayerId(str(uuid4())),
        name="Juan",
    )
    assert player.registrations == []
    restored = player_from_dict(player_to_dict(player))
    assert restored.registrations == []
    assert restored.name == "Juan"


def test_null_optional_stats_survive_round_trip():
    match = _make_match()
    data = match_to_dict(match)
    data["score_summary"] = None
    data["home_team_stats"] = None
    restored = match_from_dict(data)
    assert restored.score_summary is None
    assert restored.home_team_stats is None