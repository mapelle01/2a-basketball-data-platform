from uuid import uuid4

from datetime import datetime
from uuid import uuid4

from feb_score.application.repositories.in_memory import (
    InMemoryCompetitionRepository,
    InMemoryCorrectionRepository,
    InMemoryIdempotencyRepository,
    InMemoryMatchRepository,
    InMemoryPlayerRepository,
    InMemoryPublicationRepository,
    InMemoryRatingRepository,
    InMemoryStandingRepository,
    InMemoryTeamRepository,
)
from feb_score.domain.competition.model import Competition
from feb_score.domain.correction.model import CorrectionProposal
from feb_score.domain.match.model import Match
from feb_score.domain.player.model import Player
from feb_score.domain.publication.model import Publication
from feb_score.domain.ratings.model import PlayerRating
from feb_score.domain.standings.model import StandingSnapshot
from feb_score.domain.team.model import Team
from feb_score.domain.value_objects import (
    Actor,
    CompetitionId,
    ExternalId,
    MatchId,
    PlayerId,
    PublicationId,
    RatingVersion,
    SeasonCode,
    TeamId,
)


def test_in_memory_match_repository_can_save_and_fetch():
    repo = InMemoryMatchRepository()
    from datetime import datetime
    match = Match(
        external_id=ExternalId("2513600"),
        match_id=MatchId(str(uuid4())),
        competition_id=CompetitionId("comp-1"),
        season_code=SeasonCode("2025-2026"),
        round_number=1,
        home_team_id=ExternalId("team-home"),
        away_team_id=ExternalId("team-away"),
        scheduled_at=datetime(2026, 2, 1, 18, 30),
    )
    repo.save(match)
    assert repo.get_by_external_id(ExternalId("2513600")) is match
    assert list(repo.list_by_season(CompetitionId("comp-1"), SeasonCode("2025-2026"))) == [match]


def test_in_memory_player_and_team_repositories():
    player_repo = InMemoryPlayerRepository()
    team_repo = InMemoryTeamRepository()
    player = Player(external_id=ExternalId("pl-1"), player_id=PlayerId(str(uuid4())), name="Juan")
    team = Team(external_id=ExternalId("team-1"), team_id=TeamId(str(uuid4())), name="Club")
    player_repo.save(player)
    team_repo.save(team)
    assert player_repo.get_by_external_id(ExternalId("pl-1")) is player
    assert team_repo.get_by_external_id(ExternalId("team-1")) is team


def test_in_memory_competition_and_correction_repositories():
    competition_repo = InMemoryCompetitionRepository()
    correction_repo = InMemoryCorrectionRepository()
    competition = Competition(external_id=ExternalId("comp-1"), competition_id=CompetitionId(str(uuid4())), name="League")
    from feb_score.domain.value_objects import CorrectionProposalId

    proposal = CorrectionProposal(
        proposal_id=CorrectionProposalId(str(uuid4())),
        match_external_id=ExternalId("2513600"),
        proposed_by=Actor(id="editor-1", role="editor"),
        proposed_at=datetime.utcnow(),
        reason="Reason",
        changes=[],
    )
    competition_repo.save(competition)
    correction_repo.save(proposal)
    assert competition_repo.get_by_external_id(ExternalId("comp-1")) is competition
    assert correction_repo.get_by_id(proposal.proposal_id.value) is proposal


def test_in_memory_simple_repositories():
    standing_repo = InMemoryStandingRepository()
    rating_repo = InMemoryRatingRepository()
    publication_repo = InMemoryPublicationRepository()
    idempotency_repo = InMemoryIdempotencyRepository()

    from feb_score.domain.value_objects import RatingValue, SnapshotId

    standing_repo.save(
        StandingSnapshot(
            snapshot_id=SnapshotId(str(uuid4())),
            competition_id=CompetitionId("comp-1"),
            season_code=SeasonCode("2025-2026"),
            generated_at=datetime.utcnow(),
            rounds_included=1,
            matches_count=0,
            rules_version="v1",
        )
    )
    rating_repo.save(
        PlayerRating(
            player_external_id=ExternalId("pl-1"),
            season_code=SeasonCode("2025-2026"),
            rating_value=RatingValue(10.0),
            rating_version=RatingVersion("v1"),
            calculated_at=datetime.utcnow(),
        )
    )
    publication_repo.save(
        Publication(
            publication_id=PublicationId(str(uuid4())),
            title="t",
            content="c",
            template_id="tpl",
        )
    )
    assert not idempotency_repo.has_processed("abc")
    idempotency_repo.mark_processed("abc")
    assert idempotency_repo.has_processed("abc")
