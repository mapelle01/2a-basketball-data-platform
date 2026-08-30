"""Read-only database explorer — HTTP integration.

The Content Engine finds stories on its own; this is the manual counterpart, so
what matters is that the filters and the ranking say something TRUE about the
data. It writes nothing: a query is not allowed to have a side effect.
"""

from __future__ import annotations

import uuid
from datetime import date

from feb_score.domain.player.model import Player
from feb_score.domain.statistics.model import PlayerStats
from feb_score.domain.team.model import Team
from feb_score.domain.value_objects import ExternalId, PlayerId, SeasonCode, TeamId
from feb_score.infrastructure.persistence.repositories import (
    SqliteMatchStatsRepository,
    SqlitePlayerRepository,
    SqliteTeamRepository,
)

SEASON = "2024-2025"

# Ages are measured at 30 April of the season's second year (2025-04-30):
#   veteran 1985 -> 40, prime 1997 -> 27 (birthday in June), kid 2006 -> 19.
_ROSTER = [
    # pid, name, nationality, position, birth, team
    ("p1", "VETERANO, LUIS", "España", "Pívot", date(1985, 3, 1), "tA"),
    ("p2", "PRIME, MARC", "España", "Base", date(1997, 6, 15), "tA"),
    ("p3", "KID, TOMÁS", "Francia", "Alero", date(2006, 1, 20), "tB"),
]

# pid -> (games, points, rebounds, assists, steals, blocks)
_LINES = {
    "p1": (10, 200, 100, 10, 5, 20),
    "p2": (20, 300, 60, 120, 40, 2),
    "p3": (4, 60, 20, 8, 12, 1),
}


def _seed(client):
    db = client.app.state.gateway.db
    players, teams = SqlitePlayerRepository(db), SqliteTeamRepository(db)
    for tid, name in (("tA", "Basket Navarra"), ("tB", "Zornotza")):
        teams.save(Team(external_id=ExternalId(tid), team_id=TeamId(str(uuid.uuid4())),
                        name=name))
    for pid, name, nat, pos, birth, _team in _ROSTER:
        players.save(Player(external_id=ExternalId(pid), player_id=PlayerId(str(uuid.uuid4())),
                            name=name, nationality=nat, position=pos, birth_date=birth))

    stats = SqliteMatchStatsRepository(db)
    team_of = {p[0]: p[5] for p in _ROSTER}
    # One match per game played: the aggregate is the sum, so the season totals
    # come out exactly as declared above.
    for pid, (games, pts, reb, ast, stl, blk) in _LINES.items():
        for g in range(games):
            stats.save_player_stats(f"M-{pid}-{g}", SeasonCode(SEASON), [
                PlayerStats(player_external_id=pid, team_external_id=team_of[pid],
                            points=pts // games, rebounds=reb // games,
                            assists=ast // games, steals=stl // games,
                            blocks=blk // games, turnovers=1, minutes=20.0)
            ])


def _q(client, **kw):
    kw.setdefault("season", SEASON)
    qs = "&".join(f"{k}={v}" for k, v in kw.items())
    return client.get(f"/v1/explore/players?{qs}")


class TestRanking:
    def test_ranks_by_the_requested_metric(self, client):
        _seed(client)
        rows = _q(client, metric="points").json()["rows"]
        assert [r["player_external_id"] for r in rows] == ["p2", "p1", "p3"]
        rows = _q(client, metric="blocks").json()["rows"]
        assert rows[0]["player_external_id"] == "p1"

    def test_per_game_changes_the_answer(self, client):
        """The whole point of the toggle: the season leader in totals is not
        the leader per game, and the explorer must not blur the two."""
        _seed(client)
        totals = _q(client, metric="points").json()["rows"]
        avg = _q(client, metric="points", per_game=1).json()["rows"]
        assert totals[0]["player_external_id"] == "p2"       # 300 in 20 games
        assert avg[0]["player_external_id"] == "p1"          # 200 in 10 -> 20.0
        assert avg[0]["value"] == 20.0

    def test_limit_caps_the_rows_but_not_the_count(self, client):
        _seed(client)
        body = _q(client, limit=1).json()
        assert len(body["rows"]) == 1
        assert body["count"] == 3          # so the page can say "1 de 3"

    def test_an_unknown_metric_is_rejected(self, client):
        _seed(client)
        r = _q(client, metric="charisma")
        assert r.status_code == 400


class TestFilters:
    def test_by_team(self, client):
        _seed(client)
        rows = _q(client, team="tA").json()["rows"]
        assert {r["player_external_id"] for r in rows} == {"p1", "p2"}

    def test_by_nationality_and_position(self, client):
        _seed(client)
        assert [r["player_external_id"]
                for r in _q(client, nationality="Francia").json()["rows"]] == ["p3"]
        assert [r["player_external_id"]
                for r in _q(client, position="Base").json()["rows"]] == ["p2"]

    def test_by_age_window(self, client):
        """Age is taken at a fixed point in the season, not today, or the same
        query would return a different roster tomorrow."""
        _seed(client)
        assert [r["player_external_id"]
                for r in _q(client, max_age=20).json()["rows"]] == ["p3"]
        assert [r["player_external_id"]
                for r in _q(client, min_age=34).json()["rows"]] == ["p1"]
        rows = _q(client, min_age=25, max_age=30).json()["rows"]
        assert [r["player_external_id"] for r in rows] == ["p2"]

    def test_by_minimum_games(self, client):
        _seed(client)
        rows = _q(client, min_games=10).json()["rows"]
        assert {r["player_external_id"] for r in rows} == {"p1", "p2"}

    def test_filters_combine(self, client):
        _seed(client)
        body = _q(client, team="tA", position="Base").json()
        assert [r["player_external_id"] for r in body["rows"]] == ["p2"]
        assert body["count"] == 1

    def test_an_impossible_age_window_is_rejected(self, client):
        _seed(client)
        assert _q(client, min_age=30, max_age=20).status_code == 400
        assert _q(client, min_age=3).status_code == 400

    def test_a_malformed_season_is_rejected(self, client):
        assert _q(client, season="mañana").status_code == 400


class TestFacets:
    def test_facets_cover_the_whole_season_not_the_filtered_set(self, client):
        """If the dropdowns shrank to the current result, narrowing once would
        make it impossible to broaden again."""
        _seed(client)
        f = _q(client, team="tB").json()["facets"]
        assert sorted(f["nationalities"]) == ["España", "Francia"]
        assert {t["external_id"] for t in f["teams"]} == {"tA", "tB"}
        assert set(f["positions"]) == {"Alero", "Base", "Pívot"}

    def test_teams_carry_their_display_name(self, client):
        _seed(client)
        teams = {t["external_id"]: t["name"] for t in _q(client).json()["facets"]["teams"]}
        assert teams["tA"] == "Basket Navarra"


class TestRows:
    def test_a_row_carries_the_identity_and_the_raw_stats(self, client):
        _seed(client)
        row = next(r for r in _q(client).json()["rows"] if r["player_external_id"] == "p2")
        assert row["name"] == "PRIME, MARC"
        assert row["team_name"] == "Basket Navarra"
        assert row["nationality"] == "España" and row["position"] == "Base"
        assert row["age"] == 27 and row["games_played"] == 20
        assert (row["points"], row["rebounds"], row["assists"]) == (300, 60, 120)

    def test_a_row_carries_an_image_to_show(self, client):
        _seed(client)
        row = _q(client).json()["rows"][0]
        assert row["image_url"]

    def test_an_empty_season_still_answers_with_the_full_envelope(self, client):
        body = _q(client, season="1999-2000").json()
        assert body["count"] == 0 and body["rows"] == []
        assert body["metric"] == "points"            # the page reads it unconditionally
        assert body["facets"] == {"teams": [], "nationalities": [], "positions": []}


class TestReadOnly:
    def test_the_explorer_is_a_read_and_needs_no_key(self, client):
        _seed(client)
        assert _q(client).status_code == 200

    def test_the_page_is_served(self, client):
        r = client.get("/v1/explore")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]

    def test_it_never_writes(self, client):
        """A search that changed the database would be a bug with no symptom
        until it had already happened."""
        _seed(client)
        db = client.app.state.gateway.db
        tables = ("players", "teams", "match_player_stats", "domain_events")

        def snapshot():
            with db.connect() as conn:
                return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                        for t in tables}

        before = snapshot()
        _q(client, metric="assists", per_game=1, min_games=1)
        _q(client, team="tA", position="Base", max_age=40)
        assert snapshot() == before
