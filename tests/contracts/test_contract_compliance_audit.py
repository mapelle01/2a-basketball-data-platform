"""FASE 5 — GRUPO 4: CONTRACT COMPLIANCE audit tests.

Documents discrepancies between contracts/ (JSON Schema) and src/feb_score.
Checks marked xfail are KNOWN contract breaches, confirmed during the audit
(PASSED only because xfail is strict=True and the schema validation raises).

Run: python3 -m pytest tests/contracts/test_contract_compliance_audit.py -q
"""

import json
import sys
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from pathlib import Path
from uuid import uuid4

import pytest
import jsonschema
from jsonschema import FormatChecker

from feb_score.application.commands.commands import (
    ComputePlayerRatingCommand,
    CreateOrUpdateMatchCommand,
    GenerateLeaderboardCommand,
    RegisterPlayerToSquadCommand,
)
from feb_score.application.repositories.in_memory import (
    InMemoryMatchRepository,
    InMemoryPlayerRepository,
    InMemoryRatingRepository,
    InMemoryTeamRepository,
)
from feb_score.application.use_cases.handlers import (
    CreateOrUpdateMatchHandler,
    GenerateLeaderboardHandler,
    RegisterPlayerToSquadHandler,
    ComputePlayerRatingHandler,
)
from feb_score.application.validation import ContractValidationError
from feb_score.domain.match.model import Match
from feb_score.domain.player.model import Player
from feb_score.domain.team.model import Team
from feb_score.domain.value_objects import (
    Actor,
    CommandMeta,
    CompetitionId,
    ExternalId,
    MatchId,
    PlayerId,
    SeasonCode,
    TeamId,
)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))


def to_primitive(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if is_dataclass(value):
        return {k: to_primitive(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {k: to_primitive(v) for k, v in value.items()}
    if isinstance(value, list):
        return [to_primitive(v) for v in value]
    return value


def load_schema(name: str) -> dict:
    return json.loads((ROOT / name).read_text())


def validate_schema(instance, schema_path: str) -> None:
    jsonschema.validate(to_primitive(instance), load_schema(schema_path), format_checker=FormatChecker())


def command(payload, role="system"):
    return dict(
        command_id=str(uuid4()),
        meta=CommandMeta(version="1.0", issued_at=datetime(2026, 2, 1, 12, 0, 0)),
        actor=Actor(id="audit-1", role=role),
        payload=payload,
    )


def build_in_play_match(comp="unknown"):
    m = Match(
        external_id=ExternalId("2513600"),
        match_id=MatchId(str(uuid4())),
        competition_id=CompetitionId(comp),
        season_code=SeasonCode("2025-2026"),
        round_number=5,
        home_team_id=ExternalId("team-home"),
        away_team_id=ExternalId("team-away"),
        scheduled_at=datetime(2026, 2, 1, 18, 30),
    )
    from feb_score.domain.statistics.model import PlayerStats, TeamStats
    from feb_score.domain.value_objects import PeriodScore, ScoreSummary

    m.start(actor_id="system-1")
    m.clear_events()
    m.score_summary = ScoreSummary(home_score=80, away_score=77, periods=(PeriodScore(1, 40, 38), PeriodScore(2, 40, 39)))
    m.home_team_stats = TeamStats(
        team_external_id="team-home", points_for=80, points_against=77,
        field_goals_made=30, field_goals_attempted=60, three_points_made=8,
        three_points_attempted=20, free_throws_made=12, free_throws_attempted=16,
        turnovers=10, rebounds=38,
    )
    m.away_team_stats = TeamStats(
        team_external_id="team-away", points_for=77, points_against=80,
        field_goals_made=28, field_goals_attempted=62, three_points_made=7,
        three_points_attempted=18, free_throws_made=14, free_throws_attempted=18,
        turnovers=12, rebounds=34,
    )
    m.player_stats = (
        PlayerStats(player_external_id="pl-987", team_external_id="team-home", points=22, rebounds=9, assists=5),
    )
    return m


def finalized_match(comp="unknown"):
    m = build_in_play_match(comp)
    m.finalize(finalized_at=datetime(2026, 2, 1, 20, 0), actor_id="admin-1")
    return m


# --- MatchUpserted payload carries competition_id (allowed by schema now) ---
def test_match_upserted_event_matches_schema():
    mrepo = InMemoryMatchRepository()
    events = CreateOrUpdateMatchHandler(mrepo).handle(
        CreateOrUpdateMatchCommand(**command({
            "external_id": "2513600", "competition_id": "feb-competition", "season_code": "2025-2026",
            "round_number": 5, "scheduled_at": "2026-02-01T18:30:00Z",
            "home_team": {"external_id": "team-home", "name": "Home"},
            "away_team": {"external_id": "team-away", "name": "Away"},
            "source": {"id": "feb-api", "fetched_at": "2026-02-01T18:00:00Z", "s3_path": "s3://x"},
        }))
    )
    validate_schema(events[0], "contracts/events/match_upserted.v1.json")


# --- scheduled_at is required in schema; runtime validation rejects payloads without it ---
def test_create_or_update_match_requires_scheduled_at():
    mrepo = InMemoryMatchRepository()
    with pytest.raises(ContractValidationError):
        CreateOrUpdateMatchHandler(mrepo).handle(
            CreateOrUpdateMatchCommand(**command({
                "external_id": "2513601", "season_code": "2025-2026",
                "home_team": {"external_id": "t1", "name": "A"},
                "away_team": {"external_id": "t2", "name": "B"},
                "source": {"id": "feb-api", "fetched_at": "2026-02-01T18:00:00Z", "s3_path": "s3://x"},
            }))
        )


# --- MatchValidationStarted aligns to schema (external_id/match_uuid/initiator) ---
def test_match_validation_started_event_matches_schema():
    from feb_score.application.commands.commands import FinalizeMatchCommand
    from feb_score.application.use_cases.handlers import FinalizeMatchHandler

    mrepo = InMemoryMatchRepository()
    mrepo.save(finalized_match())
    events = FinalizeMatchHandler(mrepo).handle(
        FinalizeMatchCommand(**command({
            "match_external_id": "2513600", "validation_context": {"strict": True},
        }, role="admin"))
    )
    started = next(e for e in events if type(e).__name__ == "MatchValidationStarted")
    validate_schema(started, "contracts/events/match_validation_started.v1.json")


# --- MatchUpdatedByCorrection emits applied_at ---
def test_match_updated_by_correction_event_matches_schema():
    from feb_score.application.commands.commands import ApproveCorrectionCommand
    from feb_score.application.repositories.in_memory import InMemoryCorrectionRepository
    from feb_score.application.use_cases.handlers import ApproveCorrectionHandler
    from feb_score.domain.correction.model import CorrectionProposal
    from feb_score.domain.value_objects import CorrectionProposalId

    crepo = InMemoryCorrectionRepository()
    mrepo = InMemoryMatchRepository()
    mrepo.save(finalized_match(comp="feb-competition"))
    proposal = CorrectionProposal(
        proposal_id=CorrectionProposalId(str(uuid4())),
        match_external_id=ExternalId("2513600"),
        proposed_by=Actor("editor-1", "editor"),
        proposed_at=datetime(2026, 2, 2, 10, 0),
        reason="Official act corrected score",
        changes=[{"op": "update_score", "home_score": 80, "away_score": 77}],
    )
    crepo.save(proposal)
    events = ApproveCorrectionHandler(crepo, mrepo).handle(
        ApproveCorrectionCommand(**command({
            "proposal_id": proposal.proposal_id.value,
            "approved_by": {"id": "admin-1", "role": "admin"},
            "approved_at": "2026-02-02T12:00:00Z",
        }, role="admin"))
    )
    updated = next(e for e in events if type(e).__name__ == "MatchUpdatedByCorrection")
    validate_schema(updated, "contracts/events/match_updated_by_correction.v1.json")


# --- PlayerRegistered carries registration_id / registered_from; dorsal str ---
def test_player_registered_event_matches_schema():
    prepo = InMemoryPlayerRepository()
    trepo = InMemoryTeamRepository()
    prepo.save(Player(external_id=ExternalId("pl-987"), player_id=PlayerId(str(uuid4())), name="Juan"))
    trepo.save(Team(external_id=ExternalId("team-123"), team_id=TeamId(str(uuid4())), name="Club"))
    event = RegisterPlayerToSquadHandler(prepo, trepo).handle(
        RegisterPlayerToSquadCommand(**command({
            "player_external_id": "pl-987", "team_external_id": "team-123", "season_code": "2025-2026",
            "dorsal": "12", "registered_from": "2025-08-01T00:00:00Z",
        }, role="admin"))
    )
    validate_schema(event, "contracts/events/player_registered.v1.json")


# --- LeaderboardGenerated carries leaderboard_id / entries_count ---
def test_leaderboard_generated_event_matches_schema():
    event = GenerateLeaderboardHandler(InMemoryMatchRepository()).handle(
        GenerateLeaderboardCommand(**command({
            "season_code": "2025-2026", "category": "points_per_game", "min_games": 3, "top_n": 10,
        }))
    )
    validate_schema(event, "contracts/events/leaderboard_generated.v1.json")


# --- SeasonBackfillStarted emits source.origin='admin' (matches schema enum) ---
def test_season_backfill_started_event_matches_schema():
    from feb_score.application.commands.commands import BackfillSeasonCommand
    from feb_score.application.repositories.in_memory import InMemoryCompetitionRepository
    from feb_score.application.use_cases.handlers import BackfillSeasonHandler

    events = BackfillSeasonHandler(InMemoryCompetitionRepository()).handle(
        BackfillSeasonCommand(**command({
            "season_code": "2025-2026", "from_round": 1, "to_round": 38,
        }, role="admin"))
    )
    validate_schema(events[0], "contracts/events/season_backfill_started.v1.json")


# --- ComputePlayerRating honors window (all vs last_5 produce different ratings) ---
def test_compute_player_rating_window_is_respected():
    from feb_score.domain.statistics.model import PlayerStats, TeamStats
    from feb_score.domain.value_objects import ScoreSummary

    mrepo = InMemoryMatchRepository()
    rrepo = InMemoryRatingRepository()
    for i in range(7):
        m = Match(
            external_id=ExternalId(f"25136{i}"),
            match_id=MatchId(str(uuid4())),
            competition_id=CompetitionId("unknown"),
            season_code=SeasonCode("2025-2026"),
            round_number=i + 1,
            home_team_id=ExternalId("team-home"),
            away_team_id=ExternalId("team-away"),
            scheduled_at=datetime(2026, 2, 1, 18, 30) if i == 0 else datetime(2026, 2, 1 + i, 18, 30),
        )
        m.home_team_stats = TeamStats(
            team_external_id="team-home", points_for=80, points_against=70,
            field_goals_made=30, field_goals_attempted=60, three_points_made=8,
            three_points_attempted=20, free_throws_made=12, free_throws_attempted=16,
            turnovers=10, rebounds=38,
        )
        m.away_team_stats = TeamStats(
            team_external_id="team-away", points_for=70, points_against=80,
            field_goals_made=28, field_goals_attempted=62, three_points_made=7,
            three_points_attempted=18, free_throws_made=14, free_throws_attempted=18,
            turnovers=12, rebounds=34,
        )
        m.score_summary = ScoreSummary(home_score=80, away_score=70, periods=())
        m.player_stats = (
            PlayerStats(
                player_external_id="pl-987", team_external_id="team-home",
                points=10 + i, rebounds=9, assists=5,
            ),
        )
        m.finalize(finalized_at=datetime(2026, 2, 2, 20, 0), actor_id="admin-1")
        m.clear_events()
        mrepo.save(m)

    handler = ComputePlayerRatingHandler(mrepo, rrepo)
    values = []
    for window in ("all", "last_5"):
        events = handler.handle(
            ComputePlayerRatingCommand(
                **command({"player_external_id": "pl-987", "season_code": "2025-2026",
                           "window": window, "rating_version": "v1.0"})
            )
        )
        computed = next(e for e in events if type(e).__name__ == "PlayerRatingComputed")
        validate_schema(computed, "contracts/events/player_rating_computed.v1.json")
        values.append(computed.payload["rating_value"])
    assert values[0] != values[1], f"window had no effect: all={values[0]} last_5={values[1]}"


# --- Conformance confirmed: Finalize flow (validated/finalized) and others ---
def test_finalize_match_flow_conforms_except_validation_started():
    from feb_score.application.commands.commands import FinalizeMatchCommand
    from feb_score.application.use_cases.handlers import FinalizeMatchHandler

    mrepo = InMemoryMatchRepository()
    mrepo.save(build_in_play_match())
    events = FinalizeMatchHandler(mrepo).handle(
        FinalizeMatchCommand(**command({
            "match_external_id": "2513600", "validation_context": {"strict": True},
        }, role="admin"))
    )
    for e in events:
        if type(e).__name__ == "MatchValidationStarted":
            continue
        schema = {
            "MatchValidated": "contracts/events/match_validated.v1.json",
            "MatchFinalized": "contracts/events/match_finalized.v1.json",
        }[type(e).__name__]
        validate_schema(e, schema)