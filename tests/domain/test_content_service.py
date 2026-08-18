import uuid
from datetime import datetime

import pytest

from feb_score.application.repositories.in_memory import (
    InMemoryMatchRepository,
    InMemoryMatchStatsRepository,
)
from feb_score.application.use_cases.content_service import ContentService
from feb_score.domain.content.model import (
    ContentPriority,
    ContentType,
    HighlightType,
)
from feb_score.domain.errors import ContentGenerationError, MatchNotFound
from feb_score.domain.match.model import Match
from feb_score.domain.statistics.model import PlayerStats, TeamStats
from feb_score.domain.value_objects import (
    CompetitionId,
    ExternalId,
    MatchId,
    PeriodScore,
    ScoreSummary,
    SeasonCode,
)


def _make_match(
    external_id="match-001",
    home_score=82,
    away_score=75,
    round_number=10,
    home_team="team-a",
    away_team="team-b",
    periods=None,
):
    if periods is None:
        periods = (
            PeriodScore(1, 22, 18),
            PeriodScore(2, 20, 20),
            PeriodScore(3, 18, 19),
            PeriodScore(4, 22, 18),
        )
    match = Match.create(
        external_id=ExternalId(external_id),
        match_id=MatchId(str(uuid.uuid4())),
        competition_id=CompetitionId("2FEB"),
        season_code=SeasonCode("2025-2026"),
        round_number=round_number,
        home_team_id=ExternalId(home_team),
        away_team_id=ExternalId(away_team),
        scheduled_at=datetime(2026, 1, 15, 20, 0),
        source={"origin": "test"},
    )
    match.finalize(
        score_summary=ScoreSummary(
            home_score=home_score,
            away_score=away_score,
            periods=periods,
        ),
        home_team_stats=TeamStats(
            team_external_id=home_team,
            points_for=home_score,
            points_against=away_score,
            field_goals_made=30,
            field_goals_attempted=65,
            three_points_made=8,
            three_points_attempted=22,
            free_throws_made=14,
            free_throws_attempted=18,
            turnovers=12,
            rebounds=35,
        ),
        away_team_stats=TeamStats(
            team_external_id=away_team,
            points_for=away_score,
            points_against=home_score,
            field_goals_made=28,
            field_goals_attempted=62,
            three_points_made=6,
            three_points_attempted=20,
            free_throws_made=13,
            free_throws_attempted=17,
            turnovers=14,
            rebounds=33,
        ),
        player_stats=(
            PlayerStats(
                player_external_id="player-1",
                team_external_id=home_team,
                points=25,
                rebounds=8,
                assists=5,
                steals=2,
                blocks=1,
                turnovers=3,
                minutes=32.0,
                played_at=datetime(2026, 1, 15, 20, 0),
            ),
            PlayerStats(
                player_external_id="player-2",
                team_external_id=away_team,
                points=18,
                rebounds=6,
                assists=4,
                steals=1,
                blocks=0,
                turnovers=2,
                minutes=28.0,
                played_at=datetime(2026, 1, 15, 20, 0),
            ),
        ),
    )
    return match


def _setup_service(match=None):
    match_repo = InMemoryMatchRepository()
    stats_repo = InMemoryMatchStatsRepository()

    if match is None:
        match = _make_match()

    match_repo.save(match)

    stats_repo.save_team_stats(
        str(match.external_id),
        match.season_code,
        [match.home_team_stats, match.away_team_stats],
    )
    stats_repo.save_player_stats(
        str(match.external_id),
        match.season_code,
        list(match.player_stats),
    )

    service = ContentService(match_repo, stats_repo)
    return service, match


class TestContentServiceBasic:
    def test_generates_match_result(self):
        service, match = _setup_service()
        content = service.generate_match_result(str(match.external_id))

        assert content.content_type == ContentType.MATCH_RESULT
        assert content.facts.home_score == 82
        assert content.facts.away_score == 75
        assert content.facts.round_number == 10
        assert len(content.player_lines) == 2
        assert content.headline
        assert content.subheadline

    def test_match_not_found_raises(self):
        service, _ = _setup_service()
        with pytest.raises(MatchNotFound):
            service.generate_match_result("nonexistent-match")

    def test_match_without_score_raises(self):
        match = Match.create(
            external_id=ExternalId("no-score"),
            match_id=MatchId(str(uuid.uuid4())),
            competition_id=CompetitionId("2FEB"),
            season_code=SeasonCode("2025-2026"),
            round_number=1,
            home_team_id=ExternalId("team-a"),
            away_team_id=ExternalId("team-b"),
            scheduled_at=datetime(2026, 1, 15),
            source={"origin": "test"},
        )
        match_repo = InMemoryMatchRepository()
        stats_repo = InMemoryMatchStatsRepository()
        match_repo.save(match)
        service = ContentService(match_repo, stats_repo)

        with pytest.raises(ContentGenerationError):
            service.generate_match_result("no-score")


class TestContentServiceHighlights:
    def test_close_game_detected(self):
        match = _make_match(
            home_score=78,
            away_score=76,
            periods=(
                PeriodScore(1, 20, 18),
                PeriodScore(2, 18, 20),
                PeriodScore(3, 20, 19),
                PeriodScore(4, 20, 19),
            ),
        )
        service, _ = _setup_service(match)
        content = service.generate_match_result(str(match.external_id))
        types = {h.highlight_type for h in content.highlights}
        assert HighlightType.CLOSE_GAME in types
        assert content.priority in {ContentPriority.HIGH, ContentPriority.URGENT}

    def test_blowout_detected(self):
        match = _make_match(
            home_score=100,
            away_score=72,
            periods=(
                PeriodScore(1, 28, 18),
                PeriodScore(2, 25, 20),
                PeriodScore(3, 22, 16),
                PeriodScore(4, 25, 18),
            ),
        )
        service, _ = _setup_service(match)
        content = service.generate_match_result(str(match.external_id))
        types = {h.highlight_type for h in content.highlights}
        assert HighlightType.BLOWOUT in types

    def test_top_scorer_always_present(self):
        service, match = _setup_service()
        content = service.generate_match_result(str(match.external_id))
        types = {h.highlight_type for h in content.highlights}
        assert HighlightType.TOP_SCORER in types

    def test_to_dict_is_serializable(self):
        service, match = _setup_service()
        content = service.generate_match_result(str(match.external_id))
        dto = content.to_dict()

        assert isinstance(dto, dict)
        assert isinstance(dto["highlights"], list)
        assert isinstance(dto["top_performers"], list)
        assert isinstance(dto["channels"], list)
        assert dto["content_type"] == "match_result"
