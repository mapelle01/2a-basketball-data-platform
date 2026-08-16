"""FASE 23.5 — Season Analytics HTTP endpoints.

Boundary over the Application layer: every endpoint validates its parameters,
delegates the data retrieval to the ``CommandGateway`` (which in turn delegates
to ``SeasonAnalyticsService`` → ``MatchStatsRepository``) and returns a stable
envelope:

    {"season_code": "...", "items": [...], "count": n}

No SQL, no aggregation, no ranking and no metric math lives here. Reads are
public by design (same access level as the existing read endpoints, FASE 11/13).

HTTP semantics
--------------
* 400  invalid parameter (season_code / metric / limit out of range).
* 404  not used here: a season with no data returns 200 with an empty list
       (season_code is a filter, not a resource — consistent with the 23.1-23.4
       read models, where an empty season yields an empty list).
* 500  unexpected internal error (mapped by the global handlers, never leaks
       SQL/DSN/secrets).
"""

from __future__ import annotations

from typing import Annotated, Any, Dict, Generic, List, Optional, TypeVar

from fastapi import FastAPI, Query, Request
from pydantic import BaseModel

from . import errors as err

T = TypeVar("T")

MAX_LIMIT = 500


# ---------------------------------------------------------------------------
# Response schemas (documented in the auto-generated OpenAPI)
# ---------------------------------------------------------------------------

class SeasonResponse(BaseModel, Generic[T]):
    """Stable envelope for season analytics list responses."""

    season_code: str
    count: int
    items: List[T]


class PlayerAggregateItem(BaseModel):
    player_external_id: str
    season_code: str
    games_played: int
    points: int
    rebounds: int
    assists: int
    steals: int
    blocks: int
    turnovers: int
    minutes: float


class TeamAggregateItem(BaseModel):
    team_external_id: str
    season_code: str
    games_played: int
    wins: int
    losses: int
    points_for: int
    points_against: int
    field_goals_made: int
    field_goals_attempted: int
    three_points_made: int
    three_points_attempted: int
    free_throws_made: int
    free_throws_attempted: int
    turnovers: int
    rebounds: int


class PlayerLeaderboardItem(BaseModel):
    rank: int
    player_external_id: str
    season_code: str
    games_played: int
    points: int
    rebounds: int
    assists: int
    steals: int
    blocks: int
    turnovers: int
    minutes: float


class TeamLeaderboardItem(BaseModel):
    rank: int
    team_external_id: str
    season_code: str
    games_played: int
    wins: int
    losses: int
    points_for: int
    points_against: int
    point_difference: int
    win_percentage: float


class PlayerMetricsItem(BaseModel):
    player_external_id: str
    season_code: str
    games_played: int
    points: int
    points_per_game: float
    rebounds: int
    rebounds_per_game: float
    assists: int
    assists_per_game: float
    steals: int
    steals_per_game: float
    blocks: int
    blocks_per_game: float
    turnovers: int
    turnovers_per_game: float
    minutes: float
    minutes_per_game: float


class TeamMetricsItem(BaseModel):
    team_external_id: str
    season_code: str
    games_played: int
    wins: int
    losses: int
    points_for: int
    points_against: int
    points_per_game: float
    points_against_per_game: float
    point_difference_per_game: float
    win_percentage: float
    field_goals_made_per_game: float
    field_goals_attempted_per_game: float
    three_points_made_per_game: float
    three_points_attempted_per_game: float
    free_throws_made_per_game: float
    free_throws_attempted_per_game: float
    turnovers_per_game: float
    rebounds_per_game: float


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

_LIMIT_QUERY = Annotated[
    Optional[int],
    Query(description=f"Maximum number of items to return (1-{MAX_LIMIT})."),
]


def _validated_limit(limit: Optional[int]) -> Optional[int]:
    if limit is not None and not (1 <= limit <= MAX_LIMIT):
        raise ValueError(f"limit must be an integer between 1 and {MAX_LIMIT}")
    return limit


def _envelope(season_code: str, items: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"season_code": season_code, "count": len(items), "items": items}


def _invalid(message: str):
    return err.error_response(400, "INVALID_PARAMETER", message)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def register_analytics_routes(app: FastAPI) -> None:
    """Register the FASE 23.5 season analytics read endpoints."""

    # ------------------------------------------------------------- players
    @app.get(
        "/v1/seasons/{season_code}/players",
        tags=["analytics"],
        summary="Season player aggregates",
        description="SeasonPlayerStats for every player of the season "
        "(deterministic order by player_external_id).",
        response_model=SeasonResponse[PlayerAggregateItem],
    )
    def get_season_players(season_code: str, request: Request, limit: _LIMIT_QUERY = None):
        try:
            _validated_limit(limit)
            items = request.app.state.gateway.list_season_player_aggregates(season_code, limit)
        except ValueError as exc:
            return _invalid(str(exc))
        return _envelope(season_code, items)

    @app.get(
        "/v1/seasons/{season_code}/players/leaderboards",
        tags=["analytics"],
        summary="Season player leaderboard",
        description="Ranked players (positional 1..N) by a valid player metric: "
        "points, rebounds, assists, steals, blocks, turnovers, games_played. "
        "An unknown metric returns 400.",
        response_model=SeasonResponse[PlayerLeaderboardItem],
    )
    def get_season_player_leaderboard(
        season_code: str,
        request: Request,
        metric: str = Query(..., description="Player metric to rank by."),
        limit: _LIMIT_QUERY = None,
    ):
        try:
            _validated_limit(limit)
            items = request.app.state.gateway.list_season_player_leaderboard(
                season_code, metric, limit
            )
        except ValueError as exc:
            return _invalid(str(exc))
        return _envelope(season_code, items)

    @app.get(
        "/v1/seasons/{season_code}/players/metrics",
        tags=["analytics"],
        summary="Season player metrics",
        description="Per-game season metrics for every player (FASE 23.4): "
        "points_per_game, rebounds_per_game, assists_per_game, steals_per_game, "
        "blocks_per_game, turnovers_per_game, minutes_per_game.",
        response_model=SeasonResponse[PlayerMetricsItem],
    )
    def get_season_player_metrics(
        season_code: str, request: Request, limit: _LIMIT_QUERY = None
    ):
        try:
            _validated_limit(limit)
            items = request.app.state.gateway.list_season_player_metrics(season_code, limit)
        except ValueError as exc:
            return _invalid(str(exc))
        return _envelope(season_code, items)

    # ---------------------------------------------------------------- teams
    @app.get(
        "/v1/seasons/{season_code}/teams",
        tags=["analytics"],
        summary="Season team aggregates",
        description="SeasonTeamStats for every team of the season "
        "(deterministic order by team_external_id).",
        response_model=SeasonResponse[TeamAggregateItem],
    )
    def get_season_teams(season_code: str, request: Request, limit: _LIMIT_QUERY = None):
        try:
            _validated_limit(limit)
            items = request.app.state.gateway.list_season_team_aggregates(season_code, limit)
        except ValueError as exc:
            return _invalid(str(exc))
        return _envelope(season_code, items)

    @app.get(
        "/v1/seasons/{season_code}/teams/leaderboards",
        tags=["analytics"],
        summary="Season team leaderboard / classification",
        description="Ranked teams (positional 1..N) by a valid team metric: "
        "classification (wins DESC, losses ASC, point_difference DESC), "
        "points_for, point_difference, win_percentage. "
        "An unknown metric returns 400.",
        response_model=SeasonResponse[TeamLeaderboardItem],
    )
    def get_season_team_leaderboard(
        season_code: str,
        request: Request,
        metric: str = Query(..., description="Team metric to rank by."),
        limit: _LIMIT_QUERY = None,
    ):
        try:
            _validated_limit(limit)
            items = request.app.state.gateway.list_season_team_leaderboard(
                season_code, metric, limit
            )
        except ValueError as exc:
            return _invalid(str(exc))
        return _envelope(season_code, items)

    @app.get(
        "/v1/seasons/{season_code}/teams/metrics",
        tags=["analytics"],
        summary="Season team metrics",
        description="Per-game season metrics for every team (FASE 23.4): "
        "points_per_game, points_against_per_game, point_difference_per_game, "
        "win_percentage, field_goals_made/attempted_per_game, "
        "three_points_made/attempted_per_game, free_throws_made/attempted_per_game, "
        "turnovers_per_game, rebounds_per_game.",
        response_model=SeasonResponse[TeamMetricsItem],
    )
    def get_season_team_metrics(
        season_code: str, request: Request, limit: _LIMIT_QUERY = None
    ):
        try:
            _validated_limit(limit)
            items = request.app.state.gateway.list_season_team_metrics(season_code, limit)
        except ValueError as exc:
            return _invalid(str(exc))
        return _envelope(season_code, items)