"""FASE 8 — Repository contract tests.

The contract every persistence backend must satisfy: a repository must be able
to store and return a *reconstructed* aggregate (deserialize(serialize(x))), not
only a live object reference. This is exactly what a SQLite implementation will
have to do. In-memory stores pass today because values survive via serialization.
"""

from datetime import datetime
from uuid import uuid4

from feb_score.application.persistence import deserialize, serialize
from feb_score.application.repositories.in_memory import (
    InMemoryCompetitionRepository,
    InMemoryCorrectionRepository,
    InMemoryLeaderboardRepository,
    InMemoryMatchRepository,
    InMemoryPlayerRepository,
    InMemoryPublicationRepository,
    InMemoryRatingRepository,
    InMemoryStandingRepository,
    InMemoryTeamRepository,
)
from feb_score.domain.competition.model import Competition, RoundDefinition
from feb_score.domain.correction.model import CorrectionProposal
from feb_score.domain.leaderboard.model import Leaderboard, LeaderboardEntry
from feb_score.domain.match.model import Match
from feb_score.domain.player.model import Player
from feb_score.domain.publication.model import Publication
from feb_score.domain.ratings.model import PlayerRating
from feb_score.domain.standings.model import StandingEntry, StandingSnapshot
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
from feb_score.domain.statistics.model import PlayerStats, TeamStats

from test_serialization import finalized_match


def rebuilt(aggregate):
    return deserialize(serialize(aggregate))


def test_match_repository_accepts_reconstructed_aggregates():
    repo = InMemoryMatchRepository()
    original = finalized_match()
    reconstructed = rebuilt(original)

    repo.save(reconstructed)
    stored = repo.get_by_external_id(ExternalId("2513600"))

    assert stored == reconstructed
    assert stored.match_id == original.match_id
    assert stored.status.value == "FINALIZED"
    assert list(repo.list_by_season(CompetitionId("feb-comp"), SeasonCode("2025-2026"))) == [reconstructed]


def test_player_repository_accepts_reconstructed_aggregates():
    repo = InMemoryPlayerRepository()
    player = Player(external_id=ExternalId("pl-1"), player_id=PlayerId(str(uuid4())), name="Juan")
    player.register_for_team(team_external_id="team-1", season_code=SeasonCode("2025-2026"), dorsal=9)

    repo.save(rebuilt(player))
    stored = repo.get_by_external_id(ExternalId("pl-1"))
    assert stored == rebuilt(player)
    assert stored.is_registered_for("team-1", SeasonCode("2025-2026"))


def test_team_repository_accepts_reconstructed_aggregates():
    repo = InMemoryTeamRepository()
    team = Team(external_id=ExternalId("team-1"), team_id=TeamId(str(uuid4())), name="Club")
    team.add_player_registration(player_external_id="pl-1", season_code=SeasonCode("2025-2026"), dorsal=9)

    repo.save(rebuilt(team))
    assert repo.get_by_external_id(ExternalId("team-1")) == rebuilt(team)


def test_competition_repository_accepts_reconstructed_aggregates():
    repo = InMemoryCompetitionRepository()
    competition = Competition(external_id=ExternalId("comp-1"), competition_id=CompetitionId(str(uuid4())), name="League")
    season = competition.define_season(SeasonCode("2025-2026"), "rules-v1")
    season.add_round(RoundDefinition(number=1, label="Jornada 1"))

    repo.save(rebuilt(competition))
    stored = repo.get_by_external_id(ExternalId("comp-1"))
    assert stored == rebuilt(competition)
    assert stored.get_season(SeasonCode("2025-2026")).rounds[0].number == 1


def test_correction_repository_accepts_reconstructed_aggregates():
    repo = InMemoryCorrectionRepository()
    proposal = CorrectionProposal(
        proposal_id=CorrectionProposalId(str(uuid4())),
        match_external_id=ExternalId("2513600"),
        proposed_by=Actor(id="editor-1", role="editor"),
        proposed_at=datetime(2026, 2, 2, 10, 0),
        reason="Reason",
        changes=[{"op": "update_score", "home_score": 80, "away_score": 77}],
    )
    repo.save(rebuilt(proposal))
    assert repo.get_by_id(proposal.proposal_id.value) == rebuilt(proposal)


def test_leaderboard_repository_accepts_reconstructed_aggregates():
    repo = InMemoryLeaderboardRepository()
    board = Leaderboard(
        leaderboard_id=LeaderboardId(str(uuid4())),
        season_code=SeasonCode("2025-2026"),
        category="points_per_game",
        generated_at=datetime(2026, 2, 1, 23, 59, 59),
        min_games=1,
        entries=[LeaderboardEntry(player_external_id="pl-1", team_external_id="team-home", games=10, value=22.5)],
    )
    repo.save(rebuilt(board))
    assert repo.get_by_id(board.leaderboard_id) == rebuilt(board)


def test_append_only_repositories_accept_reconstructed_aggregates():
    standing = StandingSnapshot(
        snapshot_id=SnapshotId(str(uuid4())),
        competition_id=CompetitionId("comp-1"),
        season_code=SeasonCode("2025-2026"),
        generated_at=datetime(2026, 2, 1, 23, 59, 59),
        rounds_included=1,
        matches_count=1,
        rules_version="v1",
        entries=[StandingEntry(team_external_id="t", played=1, wins=1, losses=0, points_for=10, points_against=5, points_difference=5, points=2)],
    )
    rating = PlayerRating(
        player_external_id=ExternalId("pl-1"),
        season_code=SeasonCode("2025-2026"),
        rating_value=RatingValue(20.0),
        rating_version=RatingVersion("v1.0"),
        calculated_at=datetime(2026, 2, 1, 23, 59, 59),
        source_stats=[{"points": 20}],
    )
    publication = Publication(
        publication_id=PublicationId(str(uuid4())),
        title="t",
        content="c",
        template_id="tpl",
    )

    srepo = InMemoryStandingRepository()
    rrepo = InMemoryRatingRepository()
    prepo = InMemoryPublicationRepository()

    srepo.save(rebuilt(standing))
    rrepo.save(rebuilt(rating))
    prepo.save(rebuilt(publication))

    assert srepo._standings[0] == rebuilt(standing)
    assert rrepo._ratings[0] == rebuilt(rating)
    assert prepo._publications[0] == rebuilt(publication)


def test_get_missing_returns_none():
    assert InMemoryMatchRepository().get_by_external_id(ExternalId("nope")) is None
    assert InMemoryPlayerRepository().get_by_external_id(ExternalId("nope")) is None
    assert InMemoryTeamRepository().get_by_external_id(ExternalId("nope")) is None
    assert InMemoryCompetitionRepository().get_by_external_id(ExternalId("nope")) is None
    assert InMemoryCorrectionRepository().get_by_id("nope") is None
    assert InMemoryLeaderboardRepository().get_by_id(LeaderboardId(str(uuid4()))) is None