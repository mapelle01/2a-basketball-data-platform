"""Image gallery + operator overrides — HTTP integration.

Card imagery defaults to FEB; these cover the operator's ability to see every
player/team and to replace an image with one that survives a redeploy (stored
in the database, not on the ephemeral container disk).
"""

from __future__ import annotations

import uuid

from feb_score.domain.player.model import Player
from feb_score.domain.statistics.model import PlayerStats, TeamStats
from feb_score.domain.team.model import Team
from feb_score.domain.value_objects import (
    ExternalId,
    PlayerId,
    SeasonCode,
    TeamId,
)
from feb_score.infrastructure.persistence.repositories import (
    SqliteMatchStatsRepository,
    SqlitePlayerRepository,
    SqliteTeamRepository,
)

from api_helpers import auth_header

SEASON = "2024-2025"

# A 1x1 PNG — the smallest real image, enough to prove bytes round-trip.
_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08"
    b"\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xcf\xc0"
    b"\x00\x00\x00\x03\x00\x01\xff\xff\xff\xff\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _seed_catalog(client):
    db = client.app.state.gateway.db
    SqlitePlayerRepository(db).save(
        Player(external_id=ExternalId("p1"), player_id=PlayerId(str(uuid.uuid4())),
               name="MOLINA, JAVIER")
    )
    SqliteTeamRepository(db).save(
        Team(external_id=ExternalId("tA"), team_id=TeamId(str(uuid.uuid4())),
             name="Basket Navarra")
    )
    stats = SqliteMatchStatsRepository(db)
    stats.save_player_stats("M1", SeasonCode(SEASON), [
        PlayerStats(player_external_id="p1", team_external_id="tA", points=20,
                    rebounds=5, assists=3, steals=1, blocks=0, turnovers=2, minutes=25.0),
    ])
    stats.save_team_stats("M1", SeasonCode(SEASON), [
        TeamStats(team_external_id="tA", points_for=80, points_against=70,
                  field_goals_made=30, field_goals_attempted=60, three_points_made=8,
                  three_points_attempted=22, free_throws_made=12, free_throws_attempted=16,
                  turnovers=11, rebounds=35),
    ])


class TestCatalog:
    def test_lists_players_and_teams_with_image_status(self, client):
        _seed_catalog(client)
        cat = client.get(f"/v1/images/catalog?season={SEASON}").json()
        assert cat["season_code"] == SEASON
        players = {p["external_id"]: p for p in cat["players"]}
        assert players["p1"]["name"] == "MOLINA, JAVIER"
        assert players["p1"]["has_override"] is False
        assert "imagenes.feb.es" in players["p1"]["feb_url"]
        teams = {t["external_id"]: t for t in cat["teams"]}
        assert teams["tA"]["name"] == "Basket Navarra"

    def test_players_carry_their_team_so_the_gallery_can_filter(self, client):
        _seed_catalog(client)
        cat = client.get(f"/v1/images/catalog?season={SEASON}").json()
        p1 = next(p for p in cat["players"] if p["external_id"] == "p1")
        assert p1["team_external_id"] == "tA"
        assert p1["team_name"] == "Basket Navarra"
        # a team entry has no team of its own
        assert "team_external_id" not in cat["teams"][0]

    def test_season_is_required(self, client):
        # the app maps request-validation errors to 400
        assert client.get("/v1/images/catalog").status_code == 400


class TestOverrides:
    def test_upload_then_serve_then_delete(self, client):
        _seed_catalog(client)

        # no override yet
        assert client.get("/v1/images/player/p1").status_code == 404

        up = client.put("/v1/images/player/p1", content=_PNG,
                        headers={**auth_header("system"), "Content-Type": "image/png"})
        assert up.status_code == 200, up.text
        assert up.json()["byte_size"] == len(_PNG)

        # catalog now reports the override
        cat = client.get(f"/v1/images/catalog?season={SEASON}").json()
        assert next(p for p in cat["players"] if p["external_id"] == "p1")["has_override"]

        # serve returns the exact bytes and content type
        got = client.get("/v1/images/player/p1")
        assert got.status_code == 200
        assert got.headers["content-type"].startswith("image/png")
        assert got.content == _PNG

        # remove reverts to FEB
        assert client.delete("/v1/images/player/p1", headers=auth_header("system")).status_code == 200
        assert client.get("/v1/images/player/p1").status_code == 404

    def test_upload_replaces_in_place(self, client):
        _seed_catalog(client)
        other = _PNG + b"\x00"  # different bytes
        client.put("/v1/images/team/tA", content=_PNG,
                   headers={**auth_header("system"), "Content-Type": "image/png"})
        client.put("/v1/images/team/tA", content=other,
                   headers={**auth_header("system"), "Content-Type": "image/png"})
        assert client.get("/v1/images/team/tA").content == other

    def test_upload_requires_a_key(self, client):
        r = client.put("/v1/images/player/p1", content=_PNG,
                       headers={"Content-Type": "image/png"})
        assert r.status_code == 401

    def test_rejects_a_non_image_type(self, client):
        r = client.put("/v1/images/player/p1", content=b"nope",
                       headers={**auth_header("system"), "Content-Type": "text/plain"})
        assert r.status_code == 415

    def test_rejects_an_unknown_kind(self, client):
        r = client.put("/v1/images/mascot/x", content=_PNG,
                       headers={**auth_header("system"), "Content-Type": "image/png"})
        assert r.status_code == 400

    def test_rejects_an_oversize_image(self, client):
        big = b"\x89PNG\r\n\x1a\n" + b"\x00" * (513 * 1024)
        r = client.put("/v1/images/player/p1", content=big,
                       headers={**auth_header("system"), "Content-Type": "image/png"})
        assert r.status_code == 413

    def test_delete_without_override_404s(self, client):
        r = client.delete("/v1/images/player/ghost", headers=auth_header("system"))
        assert r.status_code == 404


class TestOverrideReachesTheCard:
    """The point of an override: it must actually appear on a rendered card,
    ahead of FEB and the initials fallback."""

    def test_uploaded_photo_is_embedded_in_the_render(self, client):
        _seed_catalog(client)
        client.put("/v1/images/player/p1", content=_PNG,
                   headers={**auth_header("system"), "Content-Type": "image/png"})

        from feb_score.infrastructure.rendering.override_assets import OverrideAssetProvider
        from feb_score.infrastructure.rendering.asset_provider import StatisticalAssetProvider

        repo = client.app.state.gateway._image_override_repo
        provider = OverrideAssetProvider(repo, StatisticalAssetProvider())
        asset = provider.player_photo("p1")
        assert asset.payload_type == "data_uri"
        assert asset.source == "operator-override"
        # a player without an override still falls through to initials
        assert provider.player_photo("nobody").payload_type != "data_uri"


class TestGalleryPage:
    def test_serves_a_page(self, client):
        r = client.get("/v1/images/gallery")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/html")

    def test_page_drives_the_real_endpoints(self, client):
        html = client.get("/v1/images/gallery").text
        assert "/v1/images/catalog" in html
        assert "method:'PUT'" in html or "method:\"PUT\"" in html
        assert "sessionStorage" in html and "localStorage" in html  # key session-only
        # filters: name search, team, and the override state that drives the
        # gallery's real job — finding who still needs a photo
        assert 'id="q"' in html and 'id="teamf"' in html
        assert "has_override" in html and "'miss'" in html
