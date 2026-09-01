"""Read-only database explorer — the place to hunt for a story before there is
a card.

The Content Engine finds stories automatically. This is the manual counterpart:
filter a season's players by team, nationality, position, age or games, rank
them by any metric, and look. It writes nothing and invents nothing — every row
is a join of what is already stored (season aggregates + player catalog + bio +
team), so anything found here can be traced back the same way a generated card
is.

Routes:
  GET  /v1/explore                  the browser page (public read)
  GET  /v1/explore/players?season=  the query itself (public read)
  POST /v1/explore/card             turn a query into a queued card (auth)
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from . import errors as err
from .auth import AuthenticationProvider

_SEASON_RE = re.compile(r"^[0-9]{4}-[0-9]{2,4}$")
MAX_ROWS = 600  # the whole season loads at once; the explorer is client-side
# A basketball career fits inside this; the bound exists so a typo in the URL
# cannot turn into a filter that silently matches nothing meaningful.
AGE_MIN, AGE_MAX = 14, 60


def register_explorer_routes(app: FastAPI) -> None:

    @app.get(
        "/v1/explore",
        tags=["explorer"],
        summary="Browse the database and hunt for content ideas",
        description="A page to filter a season's players and rank them by any "
        "metric. Read-only.",
        response_class=HTMLResponse,
    )
    def explorer_page():
        return HTMLResponse(
            (Path(__file__).with_name("explorer.html")).read_text(encoding="utf-8")
        )

    @app.get(
        "/v1/seasons",
        tags=["explorer"],
        summary="List the seasons present in the database",
        description="Every season that has matches, newest first, each with its "
        "match count. Feeds the season dropdowns in the operator pages so an "
        "operator picks from what exists instead of typing a code.",
    )
    def list_seasons(request: Request):
        return {"seasons": request.app.state.gateway.list_seasons()}

    @app.post(
        "/v1/explore/round-recap",
        tags=["explorer"],
        summary="Generate the round-recap card for a round",
        status_code=201,
        description="Detects the round's stories and generates ONLY the round "
        "recap — same pipeline, validation and dedup as any card. Authenticated.",
    )
    def generate_round_recap(body: RoundRecapRequest, request: Request):
        auth: AuthenticationProvider = request.app.state.auth
        if auth.authenticate(request) is None:
            return err.error_response(401, "UNAUTHENTICATED", "API key required")
        if not _SEASON_RE.match(body.season):
            return err.error_response(
                400, "INVALID_PARAMETER", "season must look like 2024-2025")
        try:
            return request.app.state.gateway.generate_round_recap(
                body.season, body.round_number)
        except ValueError as exc:
            return err.error_response(404, "NO_RECAP", str(exc))

    @app.post(
        "/v1/explore/season-dd-leader",
        tags=["explorer"],
        summary="Season retrospective: the player with the most double-doubles",
        status_code=201,
        description="One-click season summary. Finds the double-double leader "
        "of the season and generates a hero card with the DD count as the "
        "protagonist and the triple-double count as extras. Authenticated.",
    )
    def create_season_dd_leader_card(
        body: SeasonLeaderRequest, request: Request,
        force: bool = Query(False, description="Re-render if already queued"),
        pending: bool = Query(False, description="Land as pending_review"),
    ):
        auth: AuthenticationProvider = request.app.state.auth
        if auth.authenticate(request) is None:
            return err.error_response(401, "UNAUTHENTICATED", "API key required")
        if not _SEASON_RE.match(body.season):
            return err.error_response(
                400, "INVALID_PARAMETER", "season must look like 2024-2025")
        try:
            return request.app.state.gateway.create_season_dd_leader_card(
                body.season, force=force, pending=pending)
        except ValueError as exc:
            return err.error_response(404, "NO_DATA", str(exc))

    @app.get(
        "/v1/explore/insights",
        tags=["explorer"],
        summary="Season discovery: records, double-doubles, form",
        description="Single-game records per stat, the double-double leaders and "
        "the players trending up (recent FEB vs season FEB) — all derived from "
        "the real per-game lines. Read-only.",
    )
    def season_insights(request: Request, season: str = Query(...)):
        if not _SEASON_RE.match(season):
            return err.error_response(400, "INVALID_PARAMETER", "season must look like 2024-2025")
        return request.app.state.gateway.season_insights(season)

    @app.get(
        "/v1/explore/players",
        tags=["explorer"],
        summary="Filter and rank a season's players",
        description="Filters (team, nationality, position, age range, minimum "
        "games) narrow the season; `metric` ranks what is left, `per_game` "
        "divides by games played. `count` is the number of players that matched, "
        "`rows` is the top `limit` of them. Facets are computed over the whole "
        "season, so the dropdowns do not shrink as you narrow the search.",
    )
    def explore_players(
        request: Request,
        season: str = Query(..., description="Season code, e.g. 2024-2025"),
        team: Optional[str] = Query(None, description="Team external id"),
        nationality: Optional[str] = Query(None),
        position: Optional[str] = Query(None),
        min_age: Optional[int] = Query(None, description="Age at 30 April of the season"),
        max_age: Optional[int] = Query(None),
        min_games: Optional[int] = Query(None, ge=0),
        metric: str = Query("points"),
        per_game: bool = Query(False, description="Rank by the per-game average"),
        limit: int = Query(25, ge=1, le=MAX_ROWS),
    ):
        if not _SEASON_RE.match(season):
            return err.error_response(
                400, "INVALID_PARAMETER", "season must look like 2024-2025")
        for label, value in (("min_age", min_age), ("max_age", max_age)):
            if value is not None and not (AGE_MIN <= value <= AGE_MAX):
                return err.error_response(
                    400, "INVALID_PARAMETER",
                    f"{label} must be between {AGE_MIN} and {AGE_MAX}")
        if min_age is not None and max_age is not None and min_age > max_age:
            return err.error_response(
                400, "INVALID_PARAMETER", "min_age cannot exceed max_age")
        try:
            return request.app.state.gateway.explore_players(
                season, team=team, nationality=nationality, position=position,
                min_age=min_age, max_age=max_age, min_games=min_games,
                metric=metric, per_game=per_game, limit=limit,
            )
        except ValueError as exc:          # unknown metric
            return err.error_response(400, "INVALID_PARAMETER", str(exc))

    @app.post(
        "/v1/explore/card",
        tags=["explorer"],
        summary="Turn an explorer query into a card",
        status_code=201,
        description="Renders the query's top five (or the hand-picked players) "
        "on the ranking grid and puts the card in the review queue. The request "
        "carries the query and the wording only — every figure is re-read "
        "server-side, so a card can never claim a number the database does not "
        "have. Authenticated. A card whose copy fails fact validation is "
        "returned with the reason and is NOT queued.",
    )
    def create_card(body: CustomFiveRequest, request: Request):
        auth: AuthenticationProvider = request.app.state.auth
        if auth.authenticate(request) is None:
            return err.error_response(401, "UNAUTHENTICATED", "API key required")
        if not _SEASON_RE.match(body.season):
            return err.error_response(
                400, "INVALID_PARAMETER", "season must look like 2024-2025")
        try:
            if body.template == "hero":
                if not body.player_ids or len(body.player_ids) != 1:
                    return err.error_response(
                        400, "INVALID_PARAMETER",
                        "a single player is required for a carta individual")
                item = request.app.state.gateway.create_stat_hero(
                    body.season, player_id=body.player_ids[0], metric=body.metric,
                    per_game=body.per_game, title=body.title,
                    subtitle=body.subtitle, scope_label=body.scope_label,
                    hero_style=body.hero_style, hero_kind=body.hero_kind,
                    force=body.force, pending=body.pending)
            else:
                item = request.app.state.gateway.create_custom_five(
                    body.season, title=body.title, subtitle=body.subtitle,
                    scope_label=body.scope_label, player_ids=body.player_ids,
                    show_rank=body.show_rank, force=body.force,
                    pending=body.pending,
                    team=body.team, nationality=body.nationality,
                    position=body.position, min_age=body.min_age,
                    max_age=body.max_age, min_games=body.min_games,
                    metric=body.metric, per_game=body.per_game,
                )
        except ValueError as exc:
            return err.error_response(400, "INVALID_PARAMETER", str(exc))
        if item.get("status") in ("rejected", "failed"):
            # The operator is right there: tell them what the card claimed that
            # the data does not support, instead of leaving a dead row behind.
            return err.error_response(
                422, "CARD_REJECTED",
                item.get("error") or "the card did not pass validation",
                details={"validation": item.get("fact_validation")},
            )
        return item


class RoundRecapRequest(BaseModel):
    """A one-click round recap. Carries only the round to recap — every figure
    is re-read and re-validated server-side, same as any card."""

    season: str
    round_number: int = Field(..., ge=1, description="Round to recap")


class SeasonLeaderRequest(BaseModel):
    """A season retrospective card. Carries only the season — every figure is
    computed and validated server-side."""

    season: str


class CustomFiveRequest(BaseModel):
    """A card built from a query.

    Note what is NOT here: any figure. The request carries the QUERY and the
    words; the numbers are re-read server-side from the same place the explorer
    read them. A field for a caller-supplied statistic would be a hole straight
    through the no-invention rule.
    """

    season: str
    template: str = "grid"          # "grid" (ranking) or "hero" (single player)
    # Only used when template == "hero": "crest" is the photo-less silhouette
    # variant (default) and "photo" is the player-photo centrepiece variant.
    hero_style: str = "crest"
    # Only used when template == "hero": which NUMBER is the protagonist.
    # None lets the server default from per_game; "peak" is the single-game max
    # (what a "récord de la temporada" click actually claims).
    hero_kind: Optional[str] = None
    title: str = Field(..., min_length=1, max_length=80)
    subtitle: str = Field("", max_length=80)
    scope_label: Optional[str] = Field(None, max_length=40)
    show_rank: bool = True
    player_ids: Optional[List[str]] = None

    # the query, exactly as /v1/explore/players takes it
    team: Optional[str] = None
    nationality: Optional[str] = None
    position: Optional[str] = None
    min_age: Optional[int] = None
    max_age: Optional[int] = None
    min_games: Optional[int] = None
    metric: str = "points"
    per_game: bool = False
    # Re-render an already queued card in place (same content_id, fresh SVG).
    # Used by the modal's "Regenerar" button after a polish deploy.
    force: bool = False
    # Land as PENDING_REVIEW even when the policy would auto-approve. Ideas
    # dashboard sends this so the operator reviews every card before it
    # graduates to APROBADA.
    pending: bool = False
