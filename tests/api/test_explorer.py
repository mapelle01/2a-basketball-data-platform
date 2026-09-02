"""Read-only database explorer — HTTP integration.

The Content Engine finds stories on its own; this is the manual counterpart, so
what matters is that the filters and the ranking say something TRUE about the
data. It writes nothing: a query is not allowed to have a side effect.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from feb_score.domain.player.model import Player
from feb_score.domain.statistics.model import PlayerStats
from feb_score.domain.team.model import Team
from feb_score.domain.value_objects import ExternalId, PlayerId, SeasonCode, TeamId
from api_helpers import auth_header
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


class TestQueryToCard:
    """The bridge: a query becomes a card in the review queue.

    The invariant under test is the one that matters — the request carries the
    QUERY and the wording, never a figure, so a card cannot claim a number the
    database does not hold.
    """

    def _card(self, client, **body):
        body.setdefault("season", SEASON)
        body.setdefault("title", "Los que más anotan")
        return client.post("/v1/explore/card", json=body, headers=auth_header("editor"))

    def test_creates_a_card_from_the_current_query(self, client):
        _seed(client)
        r = self._card(client, metric="points")
        assert r.status_code == 201, r.text
        item = r.json()
        assert item["story"]["story_type"] == "custom_five"
        assert item["template_id"] == "best_five"
        names = [row["player_name"] for row in item["story"]["facts"]["lineup"]]
        assert names == ["PRIME, MARC", "VETERANO, LUIS", "KID, TOMÁS"]

    def test_the_card_lands_in_the_queue(self, client):
        _seed(client)
        content_id = self._card(client).json()["content_id"]
        queue = client.get("/v1/content/queue", headers=auth_header("editor")).json()
        items = queue["items"] if isinstance(queue, dict) else queue
        assert content_id in {i["content_id"] for i in items}

    def test_it_renders(self, client):
        _seed(client)
        content_id = self._card(client).json()["content_id"]
        svg = client.get(f"/v1/content/items/{content_id}/render.svg")
        assert svg.status_code == 200
        assert "Los que más anotan" in svg.text

    def test_the_figures_come_from_the_database_not_the_request(self, client):
        """A caller sending its own numbers must not be able to place them on a
        card. There is no field for one, and anything extra is ignored."""
        _seed(client)
        r = self._card(client, metric="points", points=9999, value="9999",
                       lineup=[{"player_name": "INVENTADO", "value": 9999}])
        assert r.status_code == 201
        facts = r.json()["story"]["facts"]
        assert "9999" not in str(facts)
        assert all(row["player_external_id"] in _LINES for row in facts["lineup"])

    def test_the_column_says_what_the_number_is(self, client):
        """The automatic quinteto ranks by FEB Rating. A card ranked by steals
        with a FEB RATING header would be lying about its own column."""
        _seed(client)
        facts = self._card(client, metric="steals").json()["story"]["facts"]
        assert facts["metric_label"] == "ROBOS"
        facts = self._card(client, metric="steals", per_game=True,
                           title="Manos rápidas").json()["story"]["facts"]
        assert facts["metric_label"] == "ROBOS POR PARTIDO"

    def test_the_supporting_line_never_repeats_the_ranked_figure(self, client):
        _seed(client)
        facts = self._card(client, metric="rebounds").json()["story"]["facts"]
        assert "REB" not in facts["lineup"][0]["context"]
        assert "PTS" in facts["lineup"][0]["context"]

    def test_hero_picks_the_crest_variant_by_default(self, client):
        """A single-player card defaults to the photo-less crest silhouette
        layout — that was the only variant before the picker existed, so
        omitting hero_style must keep landing on the same template."""
        _seed(client)
        r = self._card(client, template="hero", player_ids=["p2"], title="EL REY")
        assert r.status_code == 201, r.text
        item = r.json()
        assert item["template_id"] == "stat_hero"
        assert item["story"]["facts"]["hero_style"] == "crest"

    def test_hero_kind_peak_uses_the_single_game_max_not_the_season_average(self, client):
        """A card built from a "récord de la temporada" click MUST claim the
        single-game peak, not the season average — otherwise a 40-point record
        renders as "13,3 PPP" and the card lies about what the operator picked.
        p1 has 10 games of 20 pts each -> season 200, average 20, peak 20; use
        p2 with a spike so the peak differs from the average."""
        # Seed p1..p3 as usual, then plant one huge game for p1 so the peak
        # (40) differs cleanly from the average (~24).
        _seed(client)
        stats = SqliteMatchStatsRepository(client.app.state.gateway.db)
        stats.save_player_stats("SPIKE-p1", SeasonCode(SEASON), [
            PlayerStats(player_external_id="p1", team_external_id="tA",
                        points=40, rebounds=5, assists=1, steals=0, blocks=0,
                        turnovers=1, minutes=30.0),
        ])
        r = self._card(client, template="hero", player_ids=["p1"], title="X",
                       hero_kind="peak")
        assert r.status_code == 201, r.text
        facts = r.json()["story"]["facts"]
        assert facts["hero_value"] == "40"
        assert "EN UN PARTIDO" in facts["hero_label"]
        assert facts["hero_kind"] == "peak"
        assert facts["badge_label"] == "RÉCORD"

    def test_pending_true_routes_to_pending_review(self, client):
        """Ideas dashboard sends pending=true so operator-initiated cards land
        in PENDIENTES, not APROBADA — the human decides what actually ships."""
        _seed(client)
        r = self._card(client, template="hero", player_ids=["p2"], title="X",
                       pending=True)
        assert r.status_code == 201
        assert r.json()["status"] == "pending_review"

    def test_pending_default_uses_the_policy(self, client):
        _seed(client)
        # Without pending, custom_five with routine priority auto-approves.
        r = self._card(client)
        assert r.status_code == 201
        assert r.json()["status"] in ("approved", "pending_review")

    def test_hero_kind_defaults_from_per_game(self, client):
        _seed(client)
        avg = self._card(client, template="hero", player_ids=["p2"], title="X",
                         per_game=True).json()["story"]["facts"]
        assert avg["hero_kind"] == "average"
        tot = self._card(client, template="hero", player_ids=["p2"], title="X",
                         per_game=False).json()["story"]["facts"]
        assert tot["hero_kind"] == "total"

    def test_hero_kind_must_be_valid(self, client):
        _seed(client)
        r = self._card(client, template="hero", player_ids=["p2"], title="X",
                       hero_kind="banana")
        assert r.status_code == 400

    def test_hero_style_photo_routes_to_the_photo_layout(self, client):
        """Passing hero_style="photo" swaps the layout without changing the
        figures — the same story renders on the player-photo template."""
        _seed(client)
        r = self._card(client, template="hero", player_ids=["p2"], title="EL REY",
                       hero_style="photo")
        assert r.status_code == 201, r.text
        item = r.json()
        assert item["template_id"] == "stat_hero_photo"
        assert item["story"]["facts"]["hero_style"] == "photo"

    def test_hero_style_split_routes_to_the_streak_layout(self, client):
        """hero_style="split" is the third visual variant: giant number left,
        photo bleeding down the right. It shares the player_streak template
        with the season DD leader and the streak cards, so the whole editorial
        page has one coherent "portrait split" look wherever it appears."""
        _seed(client)
        r = self._card(client, template="hero", player_ids=["p2"], title="EL REY",
                       hero_style="split")
        assert r.status_code == 201, r.text
        item = r.json()
        assert item["template_id"] == "player_streak"
        assert item["story"]["facts"]["hero_style"] == "split"

    def test_hero_style_must_be_a_known_variant(self, client):
        _seed(client)
        r = self._card(client, template="hero", player_ids=["p2"], title="X",
                       hero_style="banana")
        assert r.status_code == 400

    def test_force_regenerates_in_place_same_content_id(self, client):
        """After a template polish deploy the operator wants a fresh SVG for
        an already-queued card without stacking a duplicate identity. force
        must keep the same content_id and update the stored SVG in place."""
        _seed(client)
        first = self._card(client, template="hero", player_ids=["p2"],
                           title="X").json()
        again = self._card(client, template="hero", player_ids=["p2"],
                           title="X", force=True).json()
        assert again["content_id"] == first["content_id"]
        # updated_at should reflect the re-render
        assert again["updated_at"] >= first["updated_at"]

    def test_hero_variants_dedup_as_separate_cards(self, client):
        """The two visual variants of the same player+metric are two DIFFERENT
        cards in the queue — a shared identity would let the second create
        return the first card, and the operator would never see the photo."""
        _seed(client)
        crest_id = self._card(client, template="hero", player_ids=["p2"],
                              title="X", hero_style="crest").json()["content_id"]
        photo_id = self._card(client, template="hero", player_ids=["p2"],
                              title="X", hero_style="photo").json()["content_id"]
        assert crest_id != photo_id

    def test_the_supporting_line_matches_the_ranked_scale(self, client):
        """A per-game ranking shows per-game supporting stats — otherwise the
        card ranks by an average and cites totals next to the name, which
        contradicts the number the card is actually claiming."""
        _seed(client)
        # p2: 20 games, 300 pts, 60 reb, 120 ast -> per game: 15 / 3 / 6.
        by_id = {row["player_external_id"]: row for row in
                 self._card(client, metric="points", per_game=True)
                 .json()["story"]["facts"]["lineup"]}
        ctx = by_id["p2"]["context"]
        assert "20 PJ" in ctx                # PJ never divides
        assert "3,0 REB" in ctx and "6,0 AST" in ctx
        assert "60 REB" not in ctx           # the season total is the wrong scale

    def test_hand_picked_players_stay_in_ranked_order(self, client):
        """Ticked in any order, drawn in the metric's order: the card numbers
        its rows, and a worse line above a better one would be a lie."""
        _seed(client)
        r = self._card(client, metric="points", player_ids=["p3", "p2"])
        ids = [row["player_external_id"] for row in r.json()["story"]["facts"]["lineup"]]
        assert ids == ["p2", "p3"]          # 300 points before 80

    def test_a_player_outside_the_query_cannot_be_added(self, client):
        _seed(client)
        r = self._card(client, position="Base", player_ids=["p1"])
        assert r.status_code == 400
        assert "p1" in r.json()["error"]["message"]

    def test_the_subtitle_states_who_was_eligible(self, client):
        _seed(client)
        facts = self._card(client, position="Base", min_games=5).json()["story"]["facts"]
        assert facts["subtitle"] == "BASE · MÍNIMO 5 PARTIDOS"

    def test_a_title_claiming_more_than_the_data_is_refused(self, client):
        """The FactValidator applies to a hand-written headline exactly as it
        does to a generated one — and the card is not queued."""
        _seed(client)
        r = self._card(client, title="Los 40 mejores")
        assert r.status_code == 422
        queue = client.get("/v1/content/queue", headers=auth_header("editor")).json()
        items = queue["items"] if isinstance(queue, dict) else queue
        assert not [i for i in items if i["story"]["facts"].get("title") == "Los 40 mejores"]

    def test_an_empty_result_makes_no_card(self, client):
        _seed(client)
        assert self._card(client, min_games=500).status_code == 400

    def test_a_title_is_required(self, client):
        _seed(client)
        # the app maps a schema rejection to 400
        assert self._card(client, title="").status_code == 400

    def test_creating_needs_a_key(self, client):
        _seed(client)
        r = client.post("/v1/explore/card", json={"season": SEASON, "title": "X"})
        assert r.status_code == 401

    def test_the_same_query_twice_is_the_same_card(self, client):
        """Re-running a query the operator liked must not fill the queue with
        copies of one card."""
        _seed(client)
        first = self._card(client).json()["content_id"]
        second = self._card(client).json()["content_id"]
        assert first == second


class TestSeasons:
    """The season dropdowns read from here, so it must list what exists — no
    more, no less — newest first."""

    def _add_match(self, client, external_id, season):
        client.run(
            "create_or_update_match",
            command_id=str(uuid.uuid4()),
            actor={"id": "t", "role": "system"},
            payload={
                "external_id": external_id, "competition_id": "segunda-feb",
                "season_code": season, "round_number": 1,
                "scheduled_at": "2025-03-15T20:00:00Z",
                "home_team": {"external_id": "h", "name": "H"},
                "away_team": {"external_id": "a", "name": "A"},
                "source": {"id": "s", "fetched_at": "2025-03-15T19:00:00Z",
                           "s3_path": "s3://x"},
            },
        ) if hasattr(client, "run") else None

    def test_lists_seasons_that_have_matches_newest_first(self, client):
        gw = client.app.state.gateway
        for eid, season in [("a", "2023-2024"), ("b", "2024-2025"),
                            ("c", "2024-2025")]:
            self._add_match(gw, eid, season)
        body = client.get("/v1/seasons").json()
        codes = [s["season_code"] for s in body["seasons"]]
        assert codes == ["2024-2025", "2023-2024"]     # newest first
        counts = {s["season_code"]: s["matches"] for s in body["seasons"]}
        assert counts["2024-2025"] == 2 and counts["2023-2024"] == 1

    def test_a_season_with_no_matches_does_not_appear(self, client):
        gw = client.app.state.gateway
        self._add_match(gw, "only", "2024-2025")
        codes = [s["season_code"] for s in client.get("/v1/seasons").json()["seasons"]]
        assert codes == ["2024-2025"]

    def test_empty_database_lists_nothing(self, client):
        assert client.get("/v1/seasons").json() == {"seasons": []}

    def test_the_throwaway_smoke_season_is_hidden(self, client):
        """The deploy smoke writes into 0000-0000 every deploy; it must never
        show up as a pickable season in the operator dropdowns."""
        gw = client.app.state.gateway
        self._add_match(gw, "real", "2024-2025")
        self._add_match(gw, "smoke-x", "0000-0000")
        codes = [s["season_code"] for s in client.get("/v1/seasons").json()["seasons"]]
        assert codes == ["2024-2025"]

    def test_it_is_a_public_read(self, client):
        assert client.get("/v1/seasons").status_code == 200


class TestFebAndVal:
    """FEB Rating (season) and VAL are derived from the per-game blobs — which
    carry shooting — so the explorer can show them without re-ingestion. They
    are None (never 0) when a player has no rateable/valuable game."""

    def _seed_with_shooting(self, client):
        from feb_score.domain.statistics.model import PlayerStats
        from feb_score.domain.value_objects import SeasonCode
        from feb_score.infrastructure.persistence.repositories import (
            SqliteMatchStatsRepository, SqlitePlayerRepository, SqliteTeamRepository)
        import uuid as _uuid
        from feb_score.domain.player.model import Player
        from feb_score.domain.team.model import Team
        from feb_score.domain.value_objects import ExternalId, PlayerId, TeamId
        db = client.app.state.gateway.db
        SqliteTeamRepository(db).save(Team(external_id=ExternalId("tA"),
            team_id=TeamId(str(_uuid.uuid4())), name="Team A"))
        SqlitePlayerRepository(db).save(Player(external_id=ExternalId("p1"),
            player_id=PlayerId(str(_uuid.uuid4())), name="STAR, ONE"))
        SqlitePlayerRepository(db).save(Player(external_id=ExternalId("p2"),
            player_id=PlayerId(str(_uuid.uuid4())), name="BENCH, TWO"))
        stats = SqliteMatchStatsRepository(db)
        def ps(pid, pts, mins, fgm, fga):
            return PlayerStats(player_external_id=pid, team_external_id="tA",
                points=pts, rebounds=6, assists=4, steals=1, blocks=0,
                turnovers=2, minutes=mins, field_goals_made=fgm,
                field_goals_attempted=fga, free_throws_made=2,
                free_throws_attempted=2, three_points_made=1, fouls=2)
        for m in ("M1", "M2"):
            stats.save_player_stats(m, SeasonCode(SEASON), [
                ps("p1", 24, 30.0, 9, 15),          # a full, rateable line
                ps("p2", 3, 6.0, 1, 2),             # under MIN_MINUTES -> no note
            ])

    def test_feb_and_val_are_present_for_a_full_line(self, client):
        self._seed_with_shooting(client)
        rows = {r["player_external_id"]: r
                for r in _q(client).json()["rows"]}
        star = rows["p1"]
        assert star["feb"] is not None and 0.0 <= star["feb"] <= 10.0
        assert star["val"] is not None and star["val"] > 0     # a season TOTAL

    def test_no_note_when_every_game_is_under_the_minute_floor(self, client):
        self._seed_with_shooting(client)
        bench = {r["player_external_id"]: r for r in _q(client).json()["rows"]}["p2"]
        assert bench["feb"] is None                            # never a fallback 0
        # VAL does not need minutes, so it is still computed
        assert bench["val"] is not None

    def test_val_is_a_season_total_summed_over_games(self, client):
        self._seed_with_shooting(client)
        star = {r["player_external_id"]: r for r in _q(client).json()["rows"]}["p1"]
        # one game's valuation, doubled (two identical games)
        from feb_score.domain.statistics.metrics import valoracion
        from feb_score.domain.statistics.model import PlayerStats
        one = valoracion(PlayerStats(player_external_id="p1", team_external_id="tA",
            points=24, rebounds=6, assists=4, steals=1, blocks=0, turnovers=2,
            minutes=30.0, field_goals_made=9, field_goals_attempted=15,
            free_throws_made=2, free_throws_attempted=2, three_points_made=1, fouls=2))
        assert star["val"] == one * 2


class TestSeasonInsights:
    """Discovery: single-game records, double-double leaders, form — all from
    the real per-game lines, never invented."""

    def _seed(self, client):
        from feb_score.domain.statistics.model import PlayerStats
        from feb_score.domain.value_objects import (SeasonCode, ExternalId, PlayerId, TeamId)
        from feb_score.domain.player.model import Player
        from feb_score.domain.team.model import Team
        from feb_score.infrastructure.persistence.repositories import (
            SqliteMatchStatsRepository, SqlitePlayerRepository, SqliteTeamRepository)
        import uuid as _uuid
        from datetime import datetime
        db = client.app.state.gateway.db
        SqliteTeamRepository(db).save(Team(external_id=ExternalId("tA"),
            team_id=TeamId(str(_uuid.uuid4())), name="Team A"))
        SqlitePlayerRepository(db).save(Player(external_id=ExternalId("star"),
            player_id=PlayerId(str(_uuid.uuid4())), name="STAR, ONE"))
        stats = SqliteMatchStatsRepository(db)
        # six games; one is a 40-point night, several are double-doubles
        for i in range(6):
            pts = 40 if i == 0 else 14 + i
            reb = 12 if i < 3 else 4       # double-doubles in the first three
            stats.save_player_stats(f"M{i}", SeasonCode(SEASON), [
                PlayerStats(player_external_id="star", team_external_id="tA",
                    points=pts, rebounds=reb, assists=3, steals=1, blocks=0,
                    turnovers=2, minutes=30.0, field_goals_made=10,
                    field_goals_attempted=16, free_throws_made=4,
                    free_throws_attempted=5, three_points_made=1, fouls=2,
                    played_at=datetime(2025, 1, 1 + i))])

    def _insights(self, client):
        return client.get(f"/v1/explore/insights?season={SEASON}").json()

    def test_points_record_is_the_best_single_game(self, client):
        self._seed(client)
        recs = {r["metric"]: r for r in self._insights(client)["records"]}
        assert recs["points"]["value"] == 40
        assert recs["points"]["player"] == "STAR, ONE"

    def test_val_and_feb_records_are_present(self, client):
        self._seed(client)
        metrics = {r["metric"] for r in self._insights(client)["records"]}
        assert "val" in metrics and "feb" in metrics

    def test_double_double_leader_is_counted(self, client):
        self._seed(client)
        dd = self._insights(client)["double_doubles"]
        assert dd and dd[0]["player_external_id"] == "star"
        assert dd[0]["count"] == 3                     # three 10+/10+ games

    def test_form_needs_six_rateable_games(self, client):
        self._seed(client)
        form = self._insights(client)["form_up"]
        assert any(f["player_external_id"] == "star" for f in form)

    def test_a_malformed_season_is_rejected(self, client):
        assert client.get("/v1/explore/insights?season=mañana").status_code == 400


class TestPhotoStatus:
    """The Media DB status shown in the rows: approved / pending / none — the
    render path still enforces the licence via select(); this is the indicator."""

    def _seed_one(self, client):
        from feb_score.domain.statistics.model import PlayerStats
        from feb_score.domain.value_objects import SeasonCode
        from feb_score.infrastructure.persistence.repositories import SqliteMatchStatsRepository
        db = client.app.state.gateway.db
        stats = SqliteMatchStatsRepository(db)
        for pid in ("has_ovr", "has_media", "nothing"):
            stats.save_player_stats("M1", SeasonCode(SEASON), [
                PlayerStats(player_external_id=pid, team_external_id="tA",
                    points=10, rebounds=4, assists=2, minutes=20.0)])
        return db

    def test_override_reads_as_approved(self, client):
        self._seed_one(client)
        client.app.state.gateway._image_override_repo.put("player", "has_ovr", b"x", "image/png")
        rows = {r["player_external_id"]: r for r in _q(client).json()["rows"]}
        assert rows["has_ovr"]["photo_status"] == "approved"

    def test_unapproved_media_reads_as_pending_and_none_otherwise(self, client):
        self._seed_one(client)
        client.app.state.gateway._media_asset_repo.add("player", "has_media", b"x", "image/png", approved=False)
        rows = {r["player_external_id"]: r for r in _q(client).json()["rows"]}
        assert rows["has_media"]["photo_status"] == "pending"
        assert rows["nothing"]["photo_status"] == "none"

    def test_approved_media_reads_as_approved(self, client):
        self._seed_one(client)
        client.app.state.gateway._media_asset_repo.add("player", "has_media", b"x", "image/png", approved=True)
        rows = {r["player_external_id"]: r for r in _q(client).json()["rows"]}
        assert rows["has_media"]["photo_status"] == "approved"


class TestHeroCard:
    """The 'carta individual' template: a single player on the photo-less hero
    layout, built from the query — figures re-read, never posted."""

    def _seed(self, client):
        from feb_score.domain.statistics.model import PlayerStats
        from feb_score.domain.value_objects import SeasonCode, ExternalId, PlayerId, TeamId
        from feb_score.domain.player.model import Player
        from feb_score.domain.team.model import Team
        from feb_score.infrastructure.persistence.repositories import (
            SqliteMatchStatsRepository, SqlitePlayerRepository, SqliteTeamRepository)
        import uuid as _uuid
        db = client.app.state.gateway.db
        SqliteTeamRepository(db).save(Team(external_id=ExternalId("tA"),
            team_id=TeamId(str(_uuid.uuid4())), name="Team A"))
        SqlitePlayerRepository(db).save(Player(external_id=ExternalId("p1"),
            player_id=PlayerId(str(_uuid.uuid4())), name="STAR, ONE"))
        stats = SqliteMatchStatsRepository(db)
        for m in ("M1", "M2"):
            stats.save_player_stats(m, SeasonCode(SEASON), [
                PlayerStats(player_external_id="p1", team_external_id="tA",
                    points=24, rebounds=6, assists=4, steals=1, blocks=0,
                    turnovers=2, minutes=30.0, field_goals_made=9,
                    field_goals_attempted=15, free_throws_made=2,
                    free_throws_attempted=2, three_points_made=1, fouls=2)])

    def test_creates_a_single_player_hero_card(self, client):
        self._seed(client)
        r = client.post("/v1/explore/card", headers=auth_header("editor"), json={
            "season": SEASON, "template": "hero", "title": "El máximo anotador",
            "player_ids": ["p1"], "metric": "points"})
        assert r.status_code == 201, r.text
        item = r.json()
        assert item["story"]["story_type"] == "custom_hero"
        assert item["template_id"] == "stat_hero"

    def test_hero_needs_exactly_one_player(self, client):
        self._seed(client)
        for ids in ([], ["p1", "p1"]):
            r = client.post("/v1/explore/card", headers=auth_header("editor"), json={
                "season": SEASON, "template": "hero", "title": "X", "player_ids": ids})
            assert r.status_code == 400


class TestStrictStreaks:
    """DESCUBRIR streaks are STRICT: consecutive games only, ordered by when they
    were played. A gap resets the count — a season total is not a streak."""

    def _seed_games(self, client, pid, name, team, per_game):
        db = client.app.state.gateway.db
        SqliteTeamRepository(db).save(Team(
            external_id=ExternalId(team), team_id=TeamId(str(uuid.uuid4())), name=team))
        SqlitePlayerRepository(db).save(Player(
            external_id=ExternalId(pid), player_id=PlayerId(str(uuid.uuid4())), name=name))
        stats = SqliteMatchStatsRepository(db)
        for i, (pts, reb, ast) in enumerate(per_game):
            stats.save_player_stats(f"M-{pid}-{i}", SeasonCode(SEASON), [
                PlayerStats(
                    player_external_id=pid, team_external_id=team,
                    points=pts, rebounds=reb, assists=ast, steals=0, blocks=0,
                    turnovers=1, minutes=25.0,
                    played_at=datetime(2025, 1, 1 + i, 18, 0)),
            ])

    def _insights(self, client):
        return client.get(f"/v1/explore/insights?season={SEASON}").json()

    def test_consecutive_20plus_counts_only_the_longest_run(self, client):
        # 22, 25, 21 (run of 3), then 10 breaks it, then 30 (run of 1).
        self._seed_games(client, "s1", "RACHA, YAGO", "T1",
                         [(22, 3, 2), (25, 4, 1), (21, 2, 2), (10, 1, 1), (30, 3, 0)])
        streaks = self._insights(client)["streaks_scoring"]
        row = next(s for s in streaks if s["player_external_id"] == "s1")
        assert row["count"] == 3
        assert row["team"] == "T1"

    def test_a_gap_resets_the_scoring_streak_below_the_floor(self, client):
        # 20+ every other game: no run reaches the floor of 3.
        self._seed_games(client, "s2", "SIERRA, PABLO", "T1",
                         [(24, 2, 1), (8, 1, 1), (26, 2, 1), (9, 1, 1), (28, 2, 1)])
        streaks = self._insights(client)["streaks_scoring"]
        assert all(s["player_external_id"] != "s2" for s in streaks)

    def test_consecutive_double_doubles(self, client):
        # DD, DD (run of 2), then a non-DD.
        self._seed_games(client, "d1", "DOBLE, IKER", "T2",
                         [(12, 11, 1), (10, 10, 2), (8, 4, 1)])
        streaks = self._insights(client)["streaks_dd"]
        row = next(s for s in streaks if s["player_external_id"] == "d1")
        assert row["count"] == 2

    def test_a_single_double_double_is_below_the_floor(self, client):
        self._seed_games(client, "d2", "UNO, MARC", "T2",
                         [(12, 11, 1), (8, 4, 1), (9, 3, 2)])
        streaks = self._insights(client)["streaks_dd"]
        assert all(s["player_external_id"] != "d2" for s in streaks)
