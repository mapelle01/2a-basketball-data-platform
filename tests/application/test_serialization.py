"""FASE 8 — Serialization round-trip tests.

Proves object -> serialize -> persist -> deserialize -> reconstruct ->
equivalent object for every aggregate, with special attention to Value Objects,
datetime, enums, IDs, lists and nested objects. Reconstructed aggregates must
keep their domain invariants (usable, validated aggregates).
"""

import json
from datetime import date, datetime
from uuid import uuid4

from feb_score.application.persistence import deserialize, serialize
from feb_score.application.persistence.serialization import SUPPORTED_TYPES
from feb_score.domain.competition.model import Competition, RoundDefinition
from feb_score.domain.correction.model import CorrectionProposal
from feb_score.domain.leaderboard.model import Leaderboard, LeaderboardEntry
from feb_score.domain.match.model import Match
from feb_score.domain.player.model import Player
from feb_score.domain.publication.model import Publication
from feb_score.domain.ratings.model import PlayerRating
from feb_score.domain.standings.model import StandingEntry, StandingSnapshot
from feb_score.domain.statistics.model import PlayerStats, TeamStats
from feb_score.domain.team.model import Team
from feb_score.domain.value_objects import (
    Actor,
    CompetitionId,
    CorrectionProposalId,
    ExternalId,
    LeaderboardId,
    MatchId,
    MatchStatus,
    PlayerId,
    PublicationId,
    RatingValue,
    RatingVersion,
    SeasonCode,
    SnapshotId,
    ScoreSummary,
    PeriodScore,
    TeamId,
)


def finalized_match() -> Match:
    match = Match(
        external_id=ExternalId("2513600"),
        match_id=MatchId(str(uuid4())),
        competition_id=CompetitionId("feb-comp"),
        season_code=SeasonCode("2025-2026"),
        round_number=5,
        home_team_id=ExternalId("team-home"),
        away_team_id=ExternalId("team-away"),
        scheduled_at=datetime(2026, 2, 1, 18, 30),
        status=MatchStatus("FINALIZED"),
        source={"id": "feb-api", "fetched_at": "2026-02-01T18:00:00Z"},
        venue={"city": "Madrid"},
        raw={"external_raw": {"key": "value"}},
        score_summary=ScoreSummary(
            home_score=80,
            away_score=77,
            periods=(PeriodScore(1, 40, 38), PeriodScore(2, 40, 39)),
        ),
        home_team_stats=TeamStats(
            team_external_id="team-home", points_for=80, points_against=77,
            field_goals_made=30, field_goals_attempted=60, three_points_made=8,
            three_points_attempted=20, free_throws_made=12, free_throws_attempted=16,
            turnovers=10, rebounds=38,
        ),
        away_team_stats=TeamStats(
            team_external_id="team-away", points_for=77, points_against=80,
            field_goals_made=28, field_goals_attempted=62, three_points_made=7,
            three_points_attempted=18, free_throws_made=14, free_throws_attempted=18,
            turnovers=12, rebounds=34,
        ),
        player_stats=(
            PlayerStats(player_external_id="pl-1", team_external_id="team-home", points=22, rebounds=9, assists=5, turnovers=2),
        ),
        version=3,
        correction_history=[
            {
                "correction_id": "corr-1", "approved_at": "2026-02-02T12:00:00",
                "approver_id": "admin-1", "reason": "fix", "previous_version": "2", "new_version": "3",
            }
        ],
    )
    match.clear_events()
    return match


def assert_roundtrip(aggregate, **mutations):
    document = serialize(aggregate)
    json.loads(json.dumps(document))  # must be JSON-safe
    reconstructed = deserialize(json.loads(json.dumps(document)))
    expected = aggregate
    for attr, value in mutations.items():
        setattr(expected, attr, value)
    assert reconstructed == expected
    return reconstructed


def test_supported_types_cover_all_persistable_aggregates():
    assert SUPPORTED_TYPES == (
        "Match", "Player", "Team", "Competition", "CorrectionProposal",
        "StandingSnapshot", "Leaderboard", "PlayerRating", "Publication",
    )


# --- Match -------------------------------------------------------------
def test_match_roundtrip_preserves_everything():
    match = finalized_match()
    reconstructed = assert_roundtrip(match)
    assert isinstance(reconstructed.status, MatchStatus)
    assert reconstructed.status.value == "FINALIZED"
    assert reconstructed.score_summary.periods[0].period == 1
    assert reconstructed.player_stats[0].player_external_id == "pl-1"
    assert reconstructed.version == 3
    assert reconstructed.correction_history[0]["new_version"] == "3"
    assert reconstructed.venue == {"city": "Madrid"}
    assert reconstructed.raw == {"external_raw": {"key": "value"}}


def test_match_roundtrip_keeps_domain_invariants():
    reconstructed = assert_roundtrip(finalized_match())
    reconstructed.validate_finalization(strict=True)  # must not raise


def test_match_roundtrip_preserves_identity_and_enum():
    match = finalized_match()
    reconstructed = deserialize(serialize(match))
    assert reconstructed.match_id == match.match_id
    assert reconstructed.external_id == match.external_id
    assert reconstructed.status == MatchStatus("FINALIZED")


# --- Player / PlayerRegistration ---------------------------------------
def test_player_registration_roundtrip_preserves_dates_dorsal_and_registration_id():
    player = Player(
        external_id=ExternalId("pl-987"),
        player_id=PlayerId(str(uuid4())),
        name="Juan",
        birth_date=date(2005, 3, 14),
        nationality="ES",
        position="PG",
    )
    reg = player.register_for_team(
        team_external_id="team-123",
        season_code=SeasonCode("2025-2026"),
        dorsal=12,
        registered_at=date(2025, 8, 1),
        registered_to=date(2026, 6, 30),
        role="starter",
    )
    reconstructed = assert_roundtrip(player)
    assert len(reconstructed.registrations) == 1
    r = reconstructed.registrations[0]
    assert r.registration_id == reg.registration_id
    assert r.dorsal == 12
    assert r.season_code == SeasonCode("2025-2026")
    assert r.registered_at == date(2025, 8, 1)
    assert r.registered_to == date(2026, 6, 30)
    assert r.role == "starter"


def test_reconstructed_player_keeps_registration_invariants():
    player = Player(external_id=ExternalId("pl-987"), player_id=PlayerId(str(uuid4())), name="Juan")
    player.register_for_team(team_external_id="team-123", season_code=SeasonCode("2025-2026"))
    reconstructed = deserialize(serialize(player))
    assert reconstructed.is_registered_for("team-123", SeasonCode("2025-2026"))
    from feb_score.domain.errors import InvalidPlayerRegistration
    import pytest

    with pytest.raises(InvalidPlayerRegistration):
        reconstructed.register_for_team(team_external_id="team-123", season_code=SeasonCode("2025-2026"))


# --- Team / TeamPlayerRegistration -------------------------------------
def test_team_registration_roundtrip_preserves_registration_id():
    team = Team(external_id=ExternalId("team-123"), team_id=TeamId(str(uuid4())), name="Club")
    reg = team.add_player_registration(player_external_id="pl-1", season_code=SeasonCode("2025-2026"), dorsal=7)
    reconstructed = assert_roundtrip(team)
    assert reconstructed.registrations[0].registration_id == reg.registration_id
    assert reconstructed.registrations[0].dorsal == 7
    assert reconstructed.has_player("pl-1", SeasonCode("2025-2026"))


# --- Competition / Season / RoundDefinition ----------------------------
def test_competition_roundtrip_preserves_seasons_and_rounds():
    competition = Competition(external_id=ExternalId("feb-comp"), competition_id=CompetitionId(str(uuid4())), name="League")
    season = competition.define_season(SeasonCode("2025-2026"), "rules-v1")
    season.add_round(RoundDefinition(number=1, label="Jornada 1"))
    season.add_round(RoundDefinition(number=2, label="Jornada 2"))

    reconstructed = assert_roundtrip(competition)
    rs = reconstructed.get_season(SeasonCode("2025-2026"))
    assert rs is not None
    assert rs.rules_version == "rules-v1"
    assert [(r.number, r.label) for r in rs.rounds] == [(1, "Jornada 1"), (2, "Jornada 2")]


# --- CorrectionProposal ------------------------------------------------
def test_correction_proposal_roundtrip_preserves_status_and_actors():
    proposal = CorrectionProposal(
        proposal_id=CorrectionProposalId(str(uuid4())),
        match_external_id=ExternalId("2513600"),
        proposed_by=Actor(id="editor-1", role="editor"),
        proposed_at=datetime(2026, 2, 2, 10, 0),
        reason="Official score confirmation",
        changes=[{"op": "update_score", "home_score": 80, "away_score": 77}],
    )
    proposal.approve(
        approver=Actor(id="admin-1", role="admin"),
        approved_at=datetime(2026, 2, 2, 12, 0),
        previous_version="2",
        new_version="3",
        comment="ok",
    )
    proposal.clear_events()
    reconstructed = assert_roundtrip(proposal)
    assert reconstructed.status == "APPROVED"
    assert reconstructed.approved_by.id == "admin-1"
    assert reconstructed.approved_at == datetime(2026, 2, 2, 12, 0)
    assert reconstructed.previous_version == "2"
    assert reconstructed.new_version == "3"
    assert reconstructed.comment == "ok"


def test_reconstructed_proposal_keeps_workflow_invariants():
    proposal = CorrectionProposal(
        proposal_id=CorrectionProposalId(str(uuid4())),
        match_external_id=ExternalId("2513600"),
        proposed_by=Actor(id="editor-1", role="editor"),
        proposed_at=datetime(2026, 2, 2, 10, 0),
        reason="Reason",
        changes=[],
    )
    proposal.clear_events()
    reconstructed = deserialize(serialize(proposal))
    reconstructed.ensure_can_be_approved_by(Actor(id="admin-1", role="admin"))  # must not raise
    from feb_score.domain.errors import UnauthorizedCorrection
    import pytest

    with pytest.raises(UnauthorizedCorrection):
        reconstructed.ensure_can_be_approved_by(Actor(id="editor-1", role="editor"))


# --- StandingSnapshot --------------------------------------------------
def test_standing_snapshot_roundtrip_preserves_entries():
    snapshot = StandingSnapshot(
        snapshot_id=SnapshotId(str(uuid4())),
        competition_id=CompetitionId("feb-comp"),
        season_code=SeasonCode("2025-2026"),
        generated_at=datetime(2026, 2, 1, 23, 59, 59),
        rounds_included=2,
        matches_count=10,
        rules_version="rules-v1",
        description="Round 2 standings",
        entries=[
            StandingEntry(
                team_external_id="team-home", played=10, wins=8, losses=2,
                points_for=800, points_against=700, points_difference=100, points=16,
            ),
            StandingEntry(
                team_external_id="team-away", played=10, wins=2, losses=8,
                points_for=700, points_against=800, points_difference=-100, points=4,
            ),
        ],
    )
    reconstructed = assert_roundtrip(snapshot)
    assert reconstructed.matches_count == 10
    assert reconstructed.rounds_included == 2
    assert reconstructed.description == "Round 2 standings"
    assert reconstructed.entries[0].points_difference == 100
    assert reconstructed.entries[1].team_external_id == "team-away"


# --- Leaderboard -------------------------------------------------------
def test_leaderboard_roundtrip_preserves_entries_and_ordering():
    board = Leaderboard(
        leaderboard_id=LeaderboardId(str(uuid4())),
        season_code=SeasonCode("2025-2026"),
        category="points_per_game",
        generated_at=datetime(2026, 2, 1, 23, 59, 59),
        min_games=1,
        entries=[
            LeaderboardEntry(player_external_id="pl-1", team_external_id="team-home", games=10, value=22.5),
            LeaderboardEntry(player_external_id="pl-2", team_external_id="team-away", games=10, value=15.0),
        ],
    )
    reconstructed = assert_roundtrip(board)
    assert reconstructed.category == "points_per_game"
    assert reconstructed.min_games == 1
    assert reconstructed.entries[0].value == 22.5
    assert reconstructed.entries[1].player_external_id == "pl-2"
    assert reconstructed.generated_at == datetime(2026, 2, 1, 23, 59, 59)


# --- PlayerRating ------------------------------------------------------
def test_rating_roundtrip_preserves_source_stats_and_values():
    rating = PlayerRating(
        player_external_id=ExternalId("pl-1"),
        season_code=SeasonCode("2025-2026"),
        rating_value=RatingValue(21.8),
        rating_version=RatingVersion("v1.0"),
        calculated_at=datetime(2026, 2, 1, 23, 59, 59),
        source_stats=[
            {
                "player_external_id": "pl-1", "team_external_id": "team-home",
                "points": 22, "rebounds": 9, "assists": 5, "steals": 0, "blocks": 0,
                "turnovers": 2, "minutes": 30.0, "played_at": "2026-02-01T18:30:00",
            }
        ],
    )
    reconstructed = assert_roundtrip(rating)
    assert reconstructed.rating_value == RatingValue(21.8)
    assert reconstructed.source_stats[0]["points"] == 22
    assert reconstructed.calculated_at == datetime(2026, 2, 1, 23, 59, 59)


# --- Publication -------------------------------------------------------
def test_publication_roundtrip_preserves_references_and_actor():
    publication = Publication(
        publication_id=PublicationId(str(uuid4())),
        title="Match report",
        content="Automated content",
        template_id="tpl-1",
        references=[{"type": "match", "id": "2513600"}],
        created_at=datetime(2026, 2, 2, 8, 0),
        created_by=Actor(id="editor-1", role="editor"),
        published_at=datetime(2026, 2, 2, 9, 0),
        status="PUBLISHED",
        locale="es",
    )
    publication.clear_events()
    reconstructed = assert_roundtrip(publication)
    assert reconstructed.references == [{"type": "match", "id": "2513600"}]
    assert reconstructed.created_by.role == "editor"
    assert reconstructed.status == "PUBLISHED"
    assert reconstructed.locale == "es"


# --- Envelope / JSON safety --------------------------------------------
def test_serialize_output_is_pure_json():
    match = finalized_match()
    document = serialize(match)
    roundtripped = json.loads(json.dumps(document))
    assert roundtripped == document


def test_datetimes_serialize_as_iso_strings():
    match = finalized_match()
    data = serialize(match)["data"]
    assert isinstance(data["scheduled_at"], str)
    assert "T" in data["scheduled_at"]


def test_unknown_type_raises():
    import pytest

    with pytest.raises(ValueError):
        serialize("not-an-aggregate")
    with pytest.raises(ValueError):
        deserialize({"type": "Unknown", "data": {}})