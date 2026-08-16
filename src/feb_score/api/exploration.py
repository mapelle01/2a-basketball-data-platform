"""FASE 24 — Match & Player Exploration HTTP endpoints.

Boundary over the Application layer (same rules as ``analytics.py``): every
endpoint validates its parameters, delegates retrieval to the ``CommandGateway``
(-> ``ExplorationService`` -> repository interfaces) and returns a stable
envelope. No SQL, no aggregation and no search math lives here. Reads are public
by design (same access level as the FASE 11/13 read endpoints).

HTTP semantics
--------------
* 400  invalid parameter (season_code / q / round_number / limit).
* 404  the referenced resource does not exist (player / team profile).
* 500  unexpected internal error (mapped by the global handlers, never leaks
       SQL/DSN/secrets).

Season filters are filters, not resources: a player/team that exists but has no
data in a season returns 200 with ``totals``/``metrics`` set to ``null`` (never
invented). Player/team identity falls back to the BoxScore stats projection
when the ``players``/``teams`` catalog has no record for the entity: the profile
still resolves (identity fields such as ``name`` are ``null``) as long as the
entity has stats in the season; 404 is reserved for entities with no data at
all. This keeps profiles and evolution usable on deployments whose catalog
tables are not yet populated (e.g. production, whose catalog is empty while the
stats projection holds 449 players / 28 teams).
"""

from __future__ import annotations

import re
from typing import Annotated, Generic, List, Optional, TypeVar

from fastapi import FastAPI, Query, Request
from pydantic import BaseModel

from . import errors as err
from .analytics import (
    MAX_LIMIT,
    PlayerAggregateItem,
    PlayerMetricsItem,
    TeamAggregateItem,
    TeamMetricsItem,
    _LIMIT_QUERY,
    _validated_limit,
)

T = TypeVar("T")

_SEASON_RE = re.compile(r"^[0-9]{4}-[0-9]{2,4}$")


# ---------------------------------------------------------------------------
# Response schemas (documented in the auto-generated OpenAPI)
# ---------------------------------------------------------------------------


class SearchResponse(BaseModel, Generic[T]):
    """Stable envelope for free-text search responses."""

    q: str
    count: int
    items: List[T]


class PlayerSearchItem(BaseModel):
    player_external_id: str
    name: str


class TeamSearchItem(BaseModel):
    team_external_id: str
    name: str


class PlayerTeamItem(BaseModel):
    team_external_id: str
    dorsal: Optional[int] = None
    role: Optional[str] = None


class PlayerProfileResponse(BaseModel):
    player_external_id: str
    name: Optional[str] = None
    position: Optional[str] = None
    nationality: Optional[str] = None
    birth_date: Optional[str] = None
    season_code: str
    teams: List[PlayerTeamItem]
    totals: Optional[PlayerAggregateItem] = None
    metrics: Optional[PlayerMetricsItem] = None


class TeamRoundEvolutionItem(BaseModel):
    round_number: int
    games_played: int
    wins: int
    losses: int
    points_for: int
    points_against: int
    point_difference: int


class TeamProfileResponse(BaseModel):
    team_external_id: str
    name: Optional[str] = None
    season_code: str
    totals: Optional[TeamAggregateItem] = None
    metrics: Optional[TeamMetricsItem] = None
    evolution: List[TeamRoundEvolutionItem]


class ScoreSummaryItem(BaseModel):
    home_score: int
    away_score: int


class MatchSearchItem(BaseModel):
    external_id: str
    match_id: str
    competition_id: str
    season_code: str
    round_number: int
    status: str
    scheduled_at: str
    home_team_id: str
    away_team_id: str
    score_summary: Optional[ScoreSummaryItem] = None


class MatchSearchResponse(BaseModel):
    """Stable envelope for the match search response."""

    season_code: str
    count: int
    items: List[MatchSearchItem]


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

_QUERY = Annotated[
    str,
    Query(..., min_length=1, description="Free-text query (case-insensitive)."),
]


def _validated_q(q: str) -> str:
    stripped = q.strip()
    if not stripped:
        raise ValueError("q must be a non-empty string")
    return stripped


def _validated_season_code(season_code: str) -> str:
    if not _SEASON_RE.match(season_code):
        raise ValueError("season_code must follow YYYY-YY or YYYY-YYYY format")
    return season_code


def _validated_round_number(round_number: Optional[int]) -> Optional[int]:
    if round_number is None:
        return None
    if round_number < 1:
        raise ValueError(f"round_number must be a positive integer, got {round_number!r}")
    return int(round_number)


def _invalid(message: str):
    return err.error_response(400, "INVALID_PARAMETER", message)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


def register_exploration_search_routes(app: FastAPI) -> None:
    """FASE 24.4 search endpoints.

    MUST be registered before ``_register_routes`` so the literal
    ``/v1/players/search``, ``/v1/teams/search`` and ``/v1/matches/search``
    paths win over the ``{external_id}`` parameter routes.
    """

    # ----------------------------------------------------- player / team search
    @app.get(
        "/v1/players/search",
        tags=["exploration"],
        summary="Search players by name",
        description="FASE 24.4 — case-insensitive substring search over player "
        "names (deterministic order by player_external_id). Wildcards in the "
        "query are treated literally.",
        response_model=SearchResponse[PlayerSearchItem],
    )
    def search_players(request: Request, q: _QUERY, limit: _LIMIT_QUERY = None):
        try:
            query = _validated_q(q)
            _validated_limit(limit)
            items = request.app.state.gateway.search_players(query, limit)
        except ValueError as exc:
            return _invalid(str(exc))
        return {"q": query, "count": len(items), "items": items}

    @app.get(
        "/v1/teams/search",
        tags=["exploration"],
        summary="Search teams by name",
        description="FASE 24.4 — case-insensitive substring search over team "
        "names (deterministic order by team_external_id). Wildcards in the "
        "query are treated literally.",
        response_model=SearchResponse[TeamSearchItem],
    )
    def search_teams(request: Request, q: _QUERY, limit: _LIMIT_QUERY = None):
        try:
            query = _validated_q(q)
            _validated_limit(limit)
            items = request.app.state.gateway.search_teams(query, limit)
        except ValueError as exc:
            return _invalid(str(exc))
        return {"q": query, "count": len(items), "items": items}

    # -------------------------------------------------------- matches search
    @app.get(
        "/v1/matches/search",
        tags=["exploration"],
        summary="Search matches",
        description="FASE 24.4 — deterministic match search. season_code is "
        "required (season isolation); competition_id, round_number, "
        "team_external_id (home OR away) and q (external_id substring) are "
        "optional AND-ed filters. Ordered by external_id.",
        response_model=MatchSearchResponse,
    )
    def search_matches(
        request: Request,
        season_code: str = Query(..., description="Season code (YYYY-YYYY)."),
        competition_id: Optional[str] = Query(
            None, description="Restrict to a competition (optional)."
        ),
        round_number: Optional[int] = Query(
            None, description="Restrict to a round number (optional)."
        ),
        team_external_id: Optional[str] = Query(
            None, description="Restrict to matches where the team is home OR away (optional)."
        ),
        q: Optional[str] = Query(
            None, description="Substring of the match external_id (optional)."
        ),
        limit: _LIMIT_QUERY = None,
    ):
        try:
            _validated_season_code(season_code)
            _validated_limit(limit)
            round_number = _validated_round_number(round_number)
            query = _validated_q(q) if q is not None else None
            items = request.app.state.gateway.search_matches(
                season_code,
                competition_id=competition_id,
                round_number=round_number,
                team_external_id=team_external_id,
                q=query,
                limit=limit,
            )
        except ValueError as exc:
            return _invalid(str(exc))
        return {"season_code": season_code, "count": len(items), "items": items}


def register_exploration_profile_routes(app: FastAPI) -> None:
    """FASE 24.2 / 24.3 profile endpoints.

    MUST be registered AFTER ``register_analytics_routes`` so the analytics
    literal ``.../players/leaderboards`` and ``.../players/metrics`` paths win
    over the ``{player_external_id}`` parameter route.
    """

    # ------------------------------------------------------- player profile
    @app.get(
        "/v1/seasons/{season_code}/players/{player_external_id}",
        tags=["exploration"],
        summary="Season player profile",
        description="FASE 24.2 — a player's profile for a season: identity, the "
        "teams they played for that season, season totals and per-game "
        "metrics. identity (name/position/nationality/birth_date) and team "
        "registrations come from the players catalog when present; without a "
        "catalog record the identity is derived from the BoxScore stats "
        "projection (name etc. null, teams = teams played for). totals/metrics "
        "are null when the player has no stats in that season.",
        response_model=PlayerProfileResponse,
    )
    def get_player_profile(season_code: str, player_external_id: str, request: Request):
        try:
            _validated_season_code(season_code)
            dto = request.app.state.gateway.get_player_profile(season_code, player_external_id)
        except ValueError as exc:
            return _invalid(str(exc))
        if dto is None:
            return err.error_response(404, "NOT_FOUND", "player not found")
        return dto

    # -------------------------------------------------------- team profile
    @app.get(
        "/v1/seasons/{season_code}/teams/{team_external_id}",
        tags=["exploration"],
        summary="Season team profile",
        description="FASE 24.3 — a team's profile for a season: identity, season "
        "totals, per-game metrics and the round-by-round evolution "
        "(ordered by round_number ASC). identity (name) comes from the teams "
        "catalog when present; without a catalog record the identity is "
        "derived from the BoxScore stats projection (name null). totals/metrics "
        "are null when the team has no stats in that season.",
        response_model=TeamProfileResponse,
    )
    def get_team_profile(season_code: str, team_external_id: str, request: Request):
        try:
            _validated_season_code(season_code)
            dto = request.app.state.gateway.get_team_profile(season_code, team_external_id)
        except ValueError as exc:
            return _invalid(str(exc))
        if dto is None:
            return err.error_response(404, "NOT_FOUND", "team not found")
        return dto


def register_exploration_routes(app: FastAPI) -> None:
    """Register all FASE 24 routes in dependency-safe order.

    Search routes first (they must precede the ``{external_id}`` routes), then
    the analytics routes and finally the profile routes. The profile routes are
    exposed separately so ``main.py`` can interleave the analytics routes in
    between; this helper keeps a single callable for convenience.
    """
    register_exploration_search_routes(app)
    register_exploration_profile_routes(app)