"""Content Engine pipeline — HTTP integration.

Seeds finalized matches + their boxscore projection directly through the
repositories (the same rows real ingestion writes), then drives the pipeline
endpoint over HTTP and verifies the queue + render endpoints. Exercises:
HTTP → gateway → LiveContentAdapter → RoundPipeline → queue → render.
"""

from __future__ import annotations

import struct
import uuid
from datetime import datetime

from feb_score.domain.match.model import Match
from feb_score.domain.player.model import Player
from feb_score.domain.statistics.model import PlayerStats, TeamStats
from feb_score.domain.team.model import Team
from feb_score.domain.value_objects import (
    CompetitionId,
    ExternalId,
    MatchId,
    PeriodScore,
    PlayerId,
    ScoreSummary,
    SeasonCode,
    TeamId,
)
from feb_score.infrastructure.persistence.connection import SqliteDatabase
from feb_score.infrastructure.persistence.repositories import (
    SqliteMatchRepository,
    SqliteMatchStatsRepository,
    SqlitePlayerRepository,
    SqliteTeamRepository,
)

import pytest

from feb_score.infrastructure.rendering import rasterizer

from api_helpers import auth_header

needs_resvg = pytest.mark.skipif(
    not rasterizer.available(), reason="resvg is not installed on this machine"
)

SEASON = "2025-2026"


def _gateway_db(client) -> SqliteDatabase:
    return client.app.state.gateway.db


def _team_stats(team, pf, pa):
    return TeamStats(
        team_external_id=team, points_for=pf, points_against=pa,
        field_goals_made=30, field_goals_attempted=60, three_points_made=8,
        three_points_attempted=22, free_throws_made=12, free_throws_attempted=16,
        turnovers=11, rebounds=35,
    )


def _seed_match(db, *, external_id, round_number, home, away, home_score, away_score, players):
    match = Match.create(
        external_id=ExternalId(external_id),
        match_id=MatchId(str(uuid.uuid4())),
        competition_id=CompetitionId("2FEB"),
        season_code=SeasonCode(SEASON),
        round_number=round_number,
        home_team_id=ExternalId(home),
        away_team_id=ExternalId(away),
        scheduled_at=datetime(2026, 2, 1, 18, 30),
        source={"origin": "test"},
    )
    home_ts = _team_stats(home, home_score, away_score)
    away_ts = _team_stats(away, away_score, home_score)
    player_stats = tuple(
        PlayerStats(
            player_external_id=p["id"], team_external_id=p["team"], points=p["pts"],
            rebounds=p.get("reb", 6), assists=p.get("ast", 4), steals=1, blocks=0,
            turnovers=2, minutes=28.0, played_at=datetime(2026, 2, 1, 18, 30),
        )
        for p in players
    )
    match.finalize(
        score_summary=ScoreSummary(
            home_score=home_score,
            away_score=away_score,
            periods=(
                PeriodScore(1, home_score // 2, away_score // 2),
                PeriodScore(2, home_score - home_score // 2, away_score - away_score // 2),
            ),
        ),
        home_team_stats=home_ts,
        away_team_stats=away_ts,
        player_stats=player_stats,
    )
    SqliteMatchRepository(db).save(match)

    stats_repo = SqliteMatchStatsRepository(db)
    stats_repo.save_team_stats(external_id, SeasonCode(SEASON), [home_ts, away_ts])
    stats_repo.save_player_stats(external_id, SeasonCode(SEASON), list(player_stats))


def _seed_round(client):
    db = _gateway_db(client)
    # Team + player catalog so names resolve.
    team_repo = SqliteTeamRepository(db)
    for tid, name in [("tA", "Basket Navarra"), ("tB", "CB Prat"), ("tC", "Fibwi Palma"), ("tD", "CB Salou")]:
        team_repo.save(Team(external_id=ExternalId(tid), team_id=TeamId(str(uuid.uuid4())), name=name))
    player_repo = SqlitePlayerRepository(db)
    for pid, name in [("p1", "F. Andrade"), ("p2", "J. Molina"), ("p3", "C. Sáez"), ("p4", "K. Toure")]:
        player_repo.save(Player(external_id=ExternalId(pid), player_id=PlayerId(str(uuid.uuid4())), name=name))

    _seed_match(
        db, external_id="2FEB_R7_M1", round_number=7, home="tA", away="tB",
        home_score=88, away_score=76,
        players=[{"id": "p1", "team": "tA", "pts": 27}, {"id": "p2", "team": "tB", "pts": 15}],
    )
    _seed_match(
        db, external_id="2FEB_R7_M2", round_number=7, home="tC", away="tD",
        home_score=104, away_score=72,
        players=[{"id": "p3", "team": "tC", "pts": 31}, {"id": "p4", "team": "tD", "pts": 20}],
    )


class TestPipelineEndpoint:
    def test_run_pipeline_generates_content(self, client):
        _seed_round(client)
        r = client.post(
            "/v1/content/pipeline/rounds/2025-2026/7", headers=auth_header("system")
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["matches_considered"] == 2
        assert body["content_generated"] >= 1
        assert "approved" in {i["status"] for i in body["items"]}

    def test_pipeline_requires_auth(self, client):
        r = client.anon().post("/v1/content/pipeline/rounds/2025-2026/7")
        assert r.status_code == 401

    def test_empty_round_generates_nothing(self, client):
        r = client.post(
            "/v1/content/pipeline/rounds/2025-2026/99", headers=auth_header("system")
        )
        assert r.status_code == 200
        body = r.json()
        assert body["matches_considered"] == 0
        assert body["content_generated"] == 0

    def test_fact_and_visual_validation_pass(self, client):
        _seed_round(client)
        body = client.post(
            "/v1/content/pipeline/rounds/2025-2026/7", headers=auth_header("system")
        ).json()
        approved = [i for i in body["items"] if i["status"] == "approved"]
        assert approved
        for item in approved:
            assert item["fact_validation"]["ok"] is True
            assert item["visual_validation"]["ok"] is True


class TestQueueAndRender:
    def test_queue_lists_generated_items(self, client):
        _seed_round(client)
        client.post("/v1/content/pipeline/rounds/2025-2026/7", headers=auth_header("system"))
        r = client.get("/v1/content/queue")
        assert r.status_code == 200
        assert r.json()["count"] >= 1

    def test_queue_filter_by_status(self, client):
        _seed_round(client)
        client.post("/v1/content/pipeline/rounds/2025-2026/7", headers=auth_header("system"))
        r = client.get("/v1/content/queue", params={"status": "approved"})
        assert r.status_code == 200
        for item in r.json()["items"]:
            assert item["status"] == "approved"

    def test_invalid_status_returns_400(self, client):
        r = client.get("/v1/content/queue", params={"status": "banana"})
        assert r.status_code == 400

    def test_render_returns_svg(self, client):
        _seed_round(client)
        run = client.post(
            "/v1/content/pipeline/rounds/2025-2026/7", headers=auth_header("system")
        ).json()
        approved = [i for i in run["items"] if i["status"] == "approved"]
        assert approved
        content_id = approved[0]["content_id"]
        r = client.get(f"/v1/content/items/{content_id}/render.svg")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("image/svg+xml")
        assert "<svg" in r.text

    def test_render_unknown_item_404(self, client):
        r = client.get(f"/v1/content/items/{uuid.uuid4()}/render.svg")
        assert r.status_code == 404


class TestDetectThenChoose:
    """Generation is opt-in per card now: detect shows every candidate without
    writing anything, then the operator generates exactly the ones they pick."""

    def test_preview_writes_nothing_and_returns_keys(self, client):
        _seed_round(client)
        before = client.get("/v1/content/queue").json()["count"]
        r = client.get("/v1/content/pipeline/rounds/2025-2026/7/candidates",
                       headers=auth_header("system"))
        assert r.status_code == 200
        body = r.json()
        assert body["candidates"], "expected candidates"
        # nothing was queued by a preview
        assert client.get("/v1/content/queue").json()["count"] == before
        c = body["candidates"][0]
        assert set(c) >= {"story_key", "story_type", "family", "subject", "label", "priority"}
        assert c["family"] in {"jornada", "ficha", "temporada"}

    def test_preview_requires_a_key(self, client):
        _seed_round(client)
        r = client.get("/v1/content/pipeline/rounds/2025-2026/7/candidates")
        assert r.status_code == 401

    def test_generates_only_the_chosen_candidates(self, client):
        _seed_round(client)
        cands = client.get("/v1/content/pipeline/rounds/2025-2026/7/candidates",
                           headers=auth_header("system")).json()["candidates"]
        pick = [cands[0]["story_key"]]
        r = client.post("/v1/content/pipeline/rounds/2025-2026/7",
                        json={"story_keys": pick}, headers=auth_header("system"))
        assert r.status_code == 200
        # exactly one card was created — not the automatic top-5
        assert r.json()["content_generated"] == 1

    def test_story_keys_must_be_a_list(self, client):
        r = client.post("/v1/content/pipeline/rounds/2025-2026/7",
                        json={"story_keys": "nope"}, headers=auth_header("system"))
        assert r.status_code == 400

    def test_no_body_still_runs_the_automatic_top_n(self, client):
        _seed_round(client)
        r = client.post("/v1/content/pipeline/rounds/2025-2026/7",
                        headers=auth_header("system"))
        assert r.status_code == 200
        assert r.json()["content_generated"] >= 1


class TestPublishableImage:
    """The pipeline used to end at an SVG, which Instagram does not accept —
    one step short of a post. These cover that last step."""

    def _approved_id(self, client):
        _seed_round(client)
        run = client.post(
            "/v1/content/pipeline/rounds/2025-2026/7", headers=auth_header("system")
        ).json()
        approved = [i for i in run["items"] if i["status"] == "approved"]
        assert approved
        return approved[0]["content_id"]

    def test_unknown_item_404s_without_touching_the_rasteriser(self, client):
        r = client.get(f"/v1/content/items/{uuid.uuid4()}/render.png")
        assert r.status_code == 404

    @needs_resvg
    def test_renders_a_png_at_post_size(self, client):
        r = client.get(f"/v1/content/items/{self._approved_id(client)}/render.png")
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/png"
        assert r.content[:8] == b"\x89PNG\r\n\x1a\n"
        width, height = struct.unpack(">II", r.content[16:24])
        assert (width, height) == (1080, 1350)   # 4:5, the largest feed post

    @needs_resvg
    def test_the_image_carries_the_artwork_not_just_the_text(self, client):
        """Regression: the rasteriser resolves nothing off disk, so a card whose
        shared assets were never inlined comes out as text on a blank field —
        and still returns a perfectly valid PNG. Measured: ~1.3 MB with the
        court, ~43 KB without it."""
        r = client.get(f"/v1/content/items/{self._approved_id(client)}/render.png")
        assert len(r.content) > 300_000

    @needs_resvg
    def test_downloads_under_a_name_worth_keeping(self, client):
        r = client.get(f"/v1/content/items/{self._approved_id(client)}/render.png")
        disposition = r.headers["content-disposition"]
        assert disposition.startswith("attachment;")
        assert "febscore-" in disposition and "-j7-" in disposition
        assert disposition.isascii()          # the header is latin-1 on the wire

    @needs_resvg
    def test_size_is_bounded(self, client):
        cid = self._approved_id(client)
        assert client.get(f"/v1/content/items/{cid}/render.png?width=5000").status_code == 400
        r = client.get(f"/v1/content/items/{cid}/render.png?width=540&height=675")
        assert struct.unpack(">II", r.content[16:24]) == (540, 675)


class TestPersistenceAcrossRestart:
    def test_queue_survives_gateway_restart(self, client, client_factory, db_path):
        _seed_round(client)
        run = client.post(
            "/v1/content/pipeline/rounds/2025-2026/7", headers=auth_header("system")
        ).json()
        assert run["content_generated"] >= 1

        # New client == new gateway over the SAME db file (simulated restart).
        restarted = client_factory(db_path)
        queue = restarted.get("/v1/content/queue").json()
        assert queue["count"] == run["content_generated"]

        # An approved item still renders from the reloaded store.
        approved = [i for i in queue["items"] if i["status"] == "approved"]
        assert approved
        svg = restarted.get(f"/v1/content/items/{approved[0]['content_id']}/render.svg")
        assert svg.status_code == 200
        assert "<svg" in svg.text

    def test_rerun_does_not_duplicate(self, client):
        _seed_round(client)
        first = client.post(
            "/v1/content/pipeline/rounds/2025-2026/7", headers=auth_header("system")
        ).json()
        client.post("/v1/content/pipeline/rounds/2025-2026/7", headers=auth_header("system"))
        queue = client.get("/v1/content/queue").json()
        # Re-running the same round adds nothing new (dedup by story identity).
        assert queue["count"] == first["content_generated"]


class TestLifecycleEndpoints:
    def _run(self, client):
        _seed_round(client)
        return client.post(
            "/v1/content/pipeline/rounds/2025-2026/7", headers=auth_header("system")
        ).json()

    def test_review_approve_schedule_publish_flow(self, client):
        run = self._run(client)
        pending = [i for i in run["items"] if i["status"] == "pending_review"]
        assert pending, "expected at least one item routed to review"
        cid = pending[0]["content_id"]

        r = client.post(f"/v1/content/items/{cid}/review/approve", headers=auth_header("system"))
        assert r.status_code == 200 and r.json()["status"] == "approved"

        r = client.post(f"/v1/content/items/{cid}/schedule", headers=auth_header("system"))
        assert r.status_code == 200 and r.json()["status"] == "scheduled"

        r = client.post(f"/v1/content/items/{cid}/publish", headers=auth_header("system"))
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "published"
        assert body["publish_result"]["dry_run"] is True

    def test_illegal_transition_returns_409(self, client):
        run = self._run(client)
        # A pending_review item cannot be published directly.
        pending = [i for i in run["items"] if i["status"] == "pending_review"]
        cid = pending[0]["content_id"]
        r = client.post(f"/v1/content/items/{cid}/publish", headers=auth_header("system"))
        assert r.status_code == 409

    def test_lifecycle_requires_auth(self, client):
        run = self._run(client)
        cid = run["items"][0]["content_id"]
        r = client.anon().post(f"/v1/content/items/{cid}/review/approve")
        assert r.status_code == 401

    def test_reject_from_review(self, client):
        run = self._run(client)
        pending = [i for i in run["items"] if i["status"] == "pending_review"]
        cid = pending[0]["content_id"]
        r = client.post(
            f"/v1/content/items/{cid}/review/reject",
            json={"reason": "off-brand"},
            headers=auth_header("system"),
        )
        assert r.status_code == 200 and r.json()["status"] == "rejected"

    def test_unknown_item_404(self, client):
        r = client.post(
            f"/v1/content/items/{uuid.uuid4()}/schedule", headers=auth_header("system")
        )
        assert r.status_code == 404

    def test_mark_published_flow_from_approved(self, client):
        run = self._run(client)
        approved = [i for i in run["items"] if i["status"] == "approved"]
        assert approved, "expected an auto-approved item to mark as published"
        cid = approved[0]["content_id"]

        r = client.post(
            f"/v1/content/items/{cid}/mark-published",
            json={"external_url": "https://instagram.com/p/xyz", "note": "j7"},
            headers=auth_header("system"),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "published"
        assert body["publish_result"]["channel"] == "manual"
        assert body["publish_result"]["external_url"] == "https://instagram.com/p/xyz"

    def test_mark_published_rejects_non_approved(self, client):
        run = self._run(client)
        pending = [i for i in run["items"] if i["status"] == "pending_review"]
        cid = pending[0]["content_id"]
        r = client.post(
            f"/v1/content/items/{cid}/mark-published", headers=auth_header("system")
        )
        assert r.status_code == 409

    def test_mark_published_requires_auth(self, client):
        run = self._run(client)
        cid = run["items"][0]["content_id"]
        r = client.anon().post(f"/v1/content/items/{cid}/mark-published")
        assert r.status_code == 401

    def test_published_survives_restart(self, client, client_factory, db_path):
        run = self._run(client)
        approved = [i for i in run["items"] if i["status"] == "approved"]
        assert approved
        cid = approved[0]["content_id"]
        client.post(f"/v1/content/items/{cid}/schedule", headers=auth_header("system"))
        client.post(f"/v1/content/items/{cid}/publish", headers=auth_header("system"))

        restarted = client_factory(db_path)
        item = restarted.get(f"/v1/content/items/{cid}").json()
        assert item["status"] == "published"
        assert item["publish_result"]["dry_run"] is True


class TestEditContent:
    """Editing was the one gap the review UI could not cover: a reviewer could
    only approve or reject, never fix a title or a caption. These pin the edit
    to what it must and must not do."""

    def _pending(self, client):
        _seed_round(client)
        run = client.post(
            "/v1/content/pipeline/rounds/2025-2026/7", headers=auth_header("system")
        ).json()
        pend = [i for i in run["items"] if i["status"] == "pending_review"]
        assert pend, "need a pending-review card to edit"
        return pend[0]["content_id"]

    def test_edits_the_caption_without_touching_the_numbers(self, client):
        cid = self._pending(client)
        before = client.get(f"/v1/content/items/{cid}").json()
        r = client.patch(f"/v1/content/items/{cid}",
                         json={"caption": "Un pie escrito a mano."},
                         headers=auth_header("system"))
        assert r.status_code == 200
        after = r.json()
        assert after["copy"]["caption"] == "Un pie escrito a mano."
        assert after["edited"] is True
        # the story facts (the numbers) are untouched
        assert after["story"]["facts"]["points"] == before["story"]["facts"]["points"]

    def test_editing_the_title_re_renders_the_card(self, client):
        cid = self._pending(client)
        before = client.get(f"/v1/content/items/{cid}/render.svg").text
        r = client.patch(f"/v1/content/items/{cid}",
                         json={"section_label": "TITULAR A MANO"},
                         headers=auth_header("system"))
        assert r.status_code == 200
        after = client.get(f"/v1/content/items/{cid}/render.svg").text
        assert "TITULAR A MANO" in after
        assert after != before

    def test_a_blank_title_is_refused(self, client):
        cid = self._pending(client)
        r = client.patch(f"/v1/content/items/{cid}",
                         json={"section_label": "   "}, headers=auth_header("system"))
        assert r.status_code == 400

    def test_an_empty_edit_is_refused(self, client):
        cid = self._pending(client)
        r = client.patch(f"/v1/content/items/{cid}", json={},
                         headers=auth_header("system"))
        assert r.status_code == 400

    def test_edit_requires_a_key(self, client):
        cid = self._pending(client)
        r = client.patch(f"/v1/content/items/{cid}", json={"caption": "x"})
        assert r.status_code == 401

    def test_unknown_item_404s(self, client):
        r = client.patch(f"/v1/content/items/{uuid.uuid4()}",
                         json={"caption": "x"}, headers=auth_header("system"))
        assert r.status_code == 404

    def test_a_published_card_cannot_be_edited(self, client):
        cid = self._pending(client)
        client.post(f"/v1/content/items/{cid}/review/approve", headers=auth_header("system"))
        client.post(f"/v1/content/items/{cid}/schedule", headers=auth_header("system"))
        client.post(f"/v1/content/items/{cid}/publish", headers=auth_header("system"))
        r = client.patch(f"/v1/content/items/{cid}",
                         json={"caption": "tarde"}, headers=auth_header("system"))
        assert r.status_code == 409


class TestReviewPage:
    """The queue had no interface at all: reviewing meant hand-written curl."""

    def test_serves_a_page(self, client):
        r = client.get("/v1/content/review")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/html")

    def test_page_drives_the_real_endpoints(self, client):
        """Guard against the page drifting from the API it calls."""
        html = client.get("/v1/content/review").text
        assert "/v1/content/queue" in html
        assert "/review/${verb}" in html          # the verb is built per action
        assert "'approve'" in html
        assert "/render.svg" in html
        assert "/render.png" in html          # the publishable image is reachable
        # the page can generate a round itself, not only via terminal curl
        assert "/v1/content/pipeline/rounds/" in html
        assert "clipboard" in html            # copy-caption for one-shot publishing
        assert "PATCH" in html                # hand-edit title + caption in place
        assert "section_label" in html and "caption" in html
        assert "/candidates" in html          # detect-then-choose preview
        assert "story_keys" in html           # generate only the picked ones
        # /v1/content/queue/purge dejó de estar en la UI — Descartar por fila
        # cubre la limpieza; el endpoint sigue existiendo por si acaso.

    def test_key_is_never_persisted_beyond_the_tab(self, client):
        html = client.get("/v1/content/review").text
        assert "sessionStorage" in html
        assert "localStorage" not in html   # would outlive the tab, on disk


class TestRoundRecapFromExplorer:
    """One-click round recap from the Explorer: it must run the SAME pipeline
    (detect -> generate just the recap), never invent, and dedup like any card."""

    def test_generates_the_round_recap_card(self, client):
        _seed_round(client)
        r = client.post(
            "/v1/explore/round-recap",
            json={"season": SEASON, "round_number": 7},
            headers=auth_header("system"),
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["created"] is True
        assert body["round_number"] == 7
        assert body["content_id"]
        # It really landed in the review queue.
        queue = client.get("/v1/content/queue").json()
        assert body["content_id"] in {i["content_id"] for i in queue["items"]}

    def test_it_needs_a_key(self, client):
        _seed_round(client)
        r = client.anon().post(
            "/v1/explore/round-recap",
            json={"season": SEASON, "round_number": 7},
        )
        assert r.status_code == 401

    def test_running_twice_does_not_duplicate(self, client):
        _seed_round(client)
        first = client.post(
            "/v1/explore/round-recap",
            json={"season": SEASON, "round_number": 7}, headers=auth_header("system"),
        ).json()
        assert first["created"] is True
        again = client.post(
            "/v1/explore/round-recap",
            json={"season": SEASON, "round_number": 7}, headers=auth_header("system"),
        ).json()
        # Same story identity -> nothing new is queued.
        assert again["created"] is False
        assert again["status"] == "already_queued"

    def test_a_round_with_no_data_has_no_recap(self, client):
        _seed_round(client)
        r = client.post(
            "/v1/explore/round-recap",
            json={"season": SEASON, "round_number": 99}, headers=auth_header("system"),
        )
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "NO_RECAP"

    def test_a_malformed_season_is_rejected(self, client):
        r = client.post(
            "/v1/explore/round-recap",
            json={"season": "nope", "round_number": 7}, headers=auth_header("system"),
        )
        assert r.status_code == 400


class TestSeasonDDLeaderFromExplorer:
    """One-click DD leader card. Server finds the leader, builds the card. All
    figures re-read here so a caller can never inject numbers onto the card."""

    def _seed_dd_leader(self, client):
        db = _gateway_db(client)
        SqliteTeamRepository(db).save(Team(
            external_id=ExternalId("tA"), team_id=TeamId(str(uuid.uuid4())),
            name="Team A"))
        SqlitePlayerRepository(db).save(Player(
            external_id=ExternalId("dd_leader"), player_id=PlayerId(str(uuid.uuid4())),
            name="MEANA PEREZ, ALONSO"))
        SqlitePlayerRepository(db).save(Player(
            external_id=ExternalId("second"), player_id=PlayerId(str(uuid.uuid4())),
            name="OTHER, PLAYER"))
        stats = SqliteMatchStatsRepository(db)
        # dd_leader: 3 DDs, 1 TD  ·  second: 1 DD  →  leader is dd_leader
        for i in range(3):
            stats.save_player_stats(f"M-A-{i}", SeasonCode(SEASON), [
                PlayerStats(player_external_id="dd_leader", team_external_id="tA",
                            points=15, rebounds=12, assists=3, steals=0, blocks=0,
                            turnovers=1, minutes=30.0),
            ])
        stats.save_player_stats("M-A-TD", SeasonCode(SEASON), [
            PlayerStats(player_external_id="dd_leader", team_external_id="tA",
                        points=22, rebounds=11, assists=10, steals=0, blocks=0,
                        turnovers=1, minutes=32.0),
        ])
        stats.save_player_stats("M-B-1", SeasonCode(SEASON), [
            PlayerStats(player_external_id="second", team_external_id="tA",
                        points=11, rebounds=10, assists=1, steals=0, blocks=0,
                        turnovers=1, minutes=25.0),
        ])

    def test_generates_a_card_for_the_dd_leader(self, client):
        self._seed_dd_leader(client)
        r = client.post("/v1/explore/season-dd-leader",
                        json={"season": SEASON}, headers=auth_header("system"))
        assert r.status_code == 201, r.text
        item = r.json()
        assert item["template_id"] == "player_streak"
        facts = item["story"]["facts"]
        assert facts["hero_value"] == 4              # 3 DDs + 1 TD (TD is a DD too)
        assert facts["td_count"] == 1
        assert facts["dd_count"] == 4
        assert "MÁS DOBLES-DOBLES" in facts["section_label"]
        assert facts["player_name"] == "MEANA PEREZ, ALONSO"

    def test_needs_a_key(self, client):
        r = client.anon().post("/v1/explore/season-dd-leader",
                               json={"season": SEASON})
        assert r.status_code == 401

    def test_a_season_with_no_dds_is_a_404(self, client):
        r = client.post("/v1/explore/season-dd-leader",
                        json={"season": "1999-2000"}, headers=auth_header("system"))
        assert r.status_code == 404

    def test_a_malformed_season_is_rejected(self, client):
        r = client.post("/v1/explore/season-dd-leader",
                        json={"season": "no"}, headers=auth_header("system"))
        assert r.status_code == 400


class TestHomeRedirect:
    """/ redirects to the Ideas dashboard — the editorial landing. Uses 307
    (temporary) so clients cache nothing that a later homepage would replace."""

    def test_root_redirects_to_ideas(self, client):
        r = client.get("/", follow_redirects=False)
        assert r.status_code == 307
        assert r.headers["location"] == "/v1/content/ideas"


class TestIdeasPage:
    """The Ideas dashboard is served as a plain HTML page, same origin as the
    API. Contents load client-side from existing endpoints (insights, seasons,
    dd-leader) — no new server data path to test here beyond the page shell."""

    def test_serves_a_page(self, client):
        r = client.get("/v1/content/ideas")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/html")
        assert "IDEAS" in r.text
        assert "Ideas del día" in r.text or "ideas del d" in r.text.lower()

    def test_page_targets_the_existing_endpoints(self, client):
        html = client.get("/v1/content/ideas").text
        assert "/v1/explore/insights" in html
        assert "/v1/explore/season-dd-leader" in html
        assert "/v1/explore/card" in html


class TestDeleteContentItem:
    """The operator asked for a way to discard cards outright — the queue only
    ever grows otherwise. DELETE /v1/content/items/{id} removes at any status."""

    def _one(self, client):
        _seed_round(client)
        run = client.post("/v1/content/pipeline/rounds/2025-2026/7",
                          headers=auth_header("system")).json()
        assert run["items"], "seed round should generate content"
        return run["items"][0]["content_id"]

    def test_deletes_at_any_status(self, client):
        cid = self._one(client)
        # The item exists.
        assert client.get(f"/v1/content/items/{cid}", headers=auth_header("system")).status_code == 200
        r = client.delete(f"/v1/content/items/{cid}", headers=auth_header("system"))
        assert r.status_code == 200
        # And it's gone from the queue.
        after = client.get(f"/v1/content/items/{cid}", headers=auth_header("system"))
        assert after.status_code == 404

    def test_unknown_id_is_404(self, client):
        r = client.delete(f"/v1/content/items/{uuid.uuid4()}",
                          headers=auth_header("system"))
        assert r.status_code == 404

    def test_delete_needs_a_key(self, client):
        cid = self._one(client)
        r = client.anon().delete(f"/v1/content/items/{cid}")
        assert r.status_code == 401


class TestEphemeralPreview:
    """Fase B: preview=true renders + validates but does NOT touch the queue.
    The card lives in an in-memory PreviewStore until the operator commits
    (moves to PENDIENTE) or discards (drops the preview)."""

    def _create_preview(self, client):
        _seed_round(client)
        # Any create endpoint with preview=true; use season-dd-leader (simpler
        # body). We seed a round; DDs will exist because _seed_round posts DD
        # lines. Point is the flag routes it into the preview store.
        # Use custom_five via /v1/explore/card which we know supports preview.
        # Fallback: use the pipeline's own path via post to round pipeline is
        # not preview-aware; stick with /v1/explore/card.
        return client.post("/v1/explore/card",
            json={"season": "2025-2026", "title": "PREVIEW", "template": "grid",
                  "preview": True, "pending": True},
            headers=auth_header("system"))

    def test_preview_returns_content_but_not_in_queue(self, client):
        r = self._create_preview(client)
        assert r.status_code == 201, r.text
        cid = r.json()["content_id"]
        # The queue does NOT know about it.
        assert client.get("/v1/content/queue").json()["items"] == [] or \
               cid not in {i["content_id"] for i in client.get("/v1/content/queue").json()["items"]}
        # But render.png works via the preview-store fallback.
        assert client.get(f"/v1/content/items/{cid}/render.svg").status_code == 200

    def test_commit_moves_preview_into_the_queue(self, client):
        cid = self._create_preview(client).json()["content_id"]
        r = client.post(f"/v1/content/preview/{cid}/commit",
                        headers=auth_header("system"))
        assert r.status_code == 201, r.text
        # Now visible in the queue.
        assert cid in {i["content_id"]
                       for i in client.get("/v1/content/queue").json()["items"]}
        # And the preview id is spent — a second commit is 404.
        assert client.post(f"/v1/content/preview/{cid}/commit",
                           headers=auth_header("system")).status_code == 404

    def test_delete_drops_a_preview(self, client):
        cid = self._create_preview(client).json()["content_id"]
        r = client.delete(f"/v1/content/items/{cid}", headers=auth_header("system"))
        assert r.status_code == 200
        # After discard the preview is gone from both stores.
        assert client.get(f"/v1/content/items/{cid}/render.svg").status_code == 404

    def test_commit_needs_a_key(self, client):
        cid = self._create_preview(client).json()["content_id"]
        r = client.anon().post(f"/v1/content/preview/{cid}/commit")
        assert r.status_code == 401

    def test_commit_of_unknown_id_is_404(self, client):
        r = client.post(f"/v1/content/preview/{uuid.uuid4()}/commit",
                        headers=auth_header("system"))
        assert r.status_code == 404
