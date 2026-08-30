"""Read-only database explorer — the place to hunt for a story before there is
a card.

The Content Engine finds stories automatically. This is the manual counterpart:
filter a season's players by team, nationality, position, age or games, rank
them by any metric, and look. It writes nothing and invents nothing — every row
is a join of what is already stored (season aggregates + player catalog + bio +
team), so anything found here can be traced back the same way a generated card
is.

Routes:
  GET /v1/explore                  the browser page (public read)
  GET /v1/explore/players?season=  the query itself (public read)
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse

from . import errors as err

_SEASON_RE = re.compile(r"^[0-9]{4}-[0-9]{2,4}$")
MAX_ROWS = 200
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
