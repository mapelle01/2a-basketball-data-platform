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
        assert "'approve'" in html and "'reject'" in html
        assert "/render.svg" in html
        assert "/render.png" in html          # the publishable image is reachable
        # the page can generate a round itself, not only via terminal curl
        assert "/v1/content/pipeline/rounds/" in html
        assert "clipboard" in html            # copy-caption for one-shot publishing
        assert "PATCH" in html                # hand-edit title + caption in place
        assert "section_label" in html and "caption" in html

    def test_key_is_never_persisted_beyond_the_tab(self, client):
        html = client.get("/v1/content/review").text
        assert "sessionStorage" in html
        assert "localStorage" not in html   # would outlive the tab, on disk
