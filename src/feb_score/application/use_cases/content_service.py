from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional, Tuple

from ..repositories.interfaces import MatchRepository, MatchStatsRepository
from ...domain.content.detection import (
    compute_priority,
    detect_match_highlights,
    generate_headline,
    generate_subheadline,
)
from ...domain.content.model import (
    Channel,
    ContentType,
    MatchFacts,
    MatchResultContent,
    PlayerLine,
    TeamLine,
)
from ...domain.errors import ContentGenerationError, MatchNotFound
from ...domain.match.model import Match
from ...domain.statistics.model import PlayerStats, TeamStats
from ...domain.value_objects import ExternalId


class ContentService:

    def __init__(
        self,
        match_repo: MatchRepository,
        stats_repo: MatchStatsRepository,
    ) -> None:
        self._matches = match_repo
        self._stats = stats_repo

    def generate_match_result(
        self,
        match_external_id: str,
        generated_at: Optional[datetime] = None,
    ) -> MatchResultContent:
        match = self._matches.get_by_external_id(ExternalId(match_external_id))
        if match is None:
            raise MatchNotFound(f"Match {match_external_id} not found")

        if match.score_summary is None:
            raise ContentGenerationError(
                f"Match {match_external_id} has no score — cannot generate content"
            )

        team_stats_list = list(self._stats.list_team_stats(match_external_id))
        player_stats_list = list(self._stats.list_player_stats(match_external_id))

        home_ts = _find_team_stats(team_stats_list, str(match.home_team_id))
        away_ts = _find_team_stats(team_stats_list, str(match.away_team_id))

        if home_ts is None or away_ts is None:
            raise ContentGenerationError(
                f"Match {match_external_id} missing team stats"
            )

        facts = _build_facts(match)
        home_team = _to_team_line(home_ts)
        away_team = _to_team_line(away_ts)
        player_lines = tuple(_to_player_line(ps) for ps in player_stats_list)

        highlights = detect_match_highlights(facts, player_lines, home_team, away_team)
        priority = compute_priority(facts, highlights)
        headline = generate_headline(facts, highlights)
        subheadline = generate_subheadline(facts, highlights, player_lines)

        generated_at = generated_at or datetime.utcnow()

        return MatchResultContent(
            content_id=str(uuid.uuid4()),
            content_type=ContentType.MATCH_RESULT,
            priority=priority,
            generated_at=generated_at,
            facts=facts,
            home_team=home_team,
            away_team=away_team,
            player_lines=player_lines,
            highlights=tuple(highlights),
            headline=headline,
            subheadline=subheadline,
            channels=(Channel.INSTAGRAM_POST, Channel.API),
        )


def _build_facts(match: Match) -> MatchFacts:
    periods = tuple(
        (p.home, p.away) for p in match.score_summary.periods
    ) if match.score_summary.periods else ()

    venue_name = None
    if match.venue and isinstance(match.venue, dict):
        venue_name = match.venue.get("name")

    return MatchFacts(
        match_external_id=str(match.external_id),
        season_code=str(match.season_code),
        round_number=match.round_number,
        scheduled_at=match.scheduled_at,
        home_team_id=str(match.home_team_id),
        away_team_id=str(match.away_team_id),
        home_score=match.score_summary.home_score,
        away_score=match.score_summary.away_score,
        periods=periods,
        venue=venue_name,
    )


def _find_team_stats(
    stats: list[TeamStats], team_external_id: str
) -> Optional[TeamStats]:
    for ts in stats:
        if ts.team_external_id == team_external_id:
            return ts
    return None


def _to_team_line(ts: TeamStats) -> TeamLine:
    return TeamLine(
        team_external_id=ts.team_external_id,
        points_for=ts.points_for,
        points_against=ts.points_against,
        field_goals_made=ts.field_goals_made,
        field_goals_attempted=ts.field_goals_attempted,
        three_points_made=ts.three_points_made,
        three_points_attempted=ts.three_points_attempted,
        free_throws_made=ts.free_throws_made,
        free_throws_attempted=ts.free_throws_attempted,
        turnovers=ts.turnovers,
        rebounds=ts.rebounds,
    )


def _to_player_line(ps: PlayerStats) -> PlayerLine:
    return PlayerLine(
        player_external_id=ps.player_external_id,
        team_external_id=ps.team_external_id,
        points=ps.points,
        rebounds=ps.rebounds,
        assists=ps.assists,
        steals=ps.steals,
        blocks=ps.blocks,
        turnovers=ps.turnovers,
        minutes=ps.minutes,
    )
